/*
 * Urban Flow - Adaptive Traffic Signal System
 * Copyright (c) 2026 Harsh Aggarwal <aggarwalharsh663@gmail.com>. All rights reserved.
 *
 * Original Author & Sole Intellectual Property Owner: Harsh Aggarwal
 * Any additions, modifications, or contributed files to this project automatically
 * and irrevocably vest all copyright and intellectual property rights solely in Harsh Aggarwal.
 */

import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import fs from 'fs';
import path from 'path';
import os from 'os';
import { EventEmitter, once } from 'events';
import { createRequire } from 'module';

const require = createRequire(import.meta.url);
const { writeChunkWithBackpressure } = require('../../electron/stream-utils.cjs');

describe('Stream Backpressure & Upload Memory Optimization', () => {
  let tmpDir: string;

  beforeEach(() => {
    tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'backpressure-test-'));
  });

  afterEach(() => {
    try {
      fs.rmSync(tmpDir, { recursive: true, force: true });
    } catch {}
  });

  it('1. Small image upload: writes immediately when buffer is below highWaterMark', async () => {
    const filePath = path.join(tmpDir, 'small_image.png');
    const ws = fs.createWriteStream(filePath);
    const chunk = Buffer.from('SMALL_IMAGE_PNG_DATA');

    await writeChunkWithBackpressure(ws, chunk);

    await new Promise<void>((resolve, reject) => {
      ws.end((err?: Error | null) => (err ? reject(err) : resolve()));
    });

    const written = fs.readFileSync(filePath);
    expect(written.toString()).toBe('SMALL_IMAGE_PNG_DATA');
  });

  it('2. Normal video upload: streams chunks with backpressure and flushes correctly', async () => {
    const filePath = path.join(tmpDir, 'normal_video.mp4');
    const ws = fs.createWriteStream(filePath, { highWaterMark: 1024 });

    const totalChunks = 50;
    const chunkSize = 2048; // Each chunk exceeds highWaterMark to trigger drain
    const chunk = Buffer.alloc(chunkSize, 'V');

    for (let i = 0; i < totalChunks; i++) {
      await writeChunkWithBackpressure(ws, chunk);
    }

    await new Promise<void>((resolve, reject) => {
      ws.end((err?: Error | null) => (err ? reject(err) : resolve()));
    });

    const stats = fs.statSync(filePath);
    expect(stats.size).toBe(totalChunks * chunkSize);
  });

  it('3. 100 MB upload simulation: memory heap remains bounded during streaming', async () => {
    const filePath = path.join(tmpDir, '100mb_sim.mp4');
    const ws = fs.createWriteStream(filePath, { highWaterMark: 64 * 1024 });

    const chunk = Buffer.alloc(64 * 1024, 0x41); // 64 KB chunk
    const iterations = 100 * 16; // 100 MB total (1600 * 64KB)

    const initialHeap = process.memoryUsage().heapUsed;

    for (let i = 0; i < iterations; i++) {
      await writeChunkWithBackpressure(ws, chunk);
    }

    await new Promise<void>((resolve, reject) => {
      ws.end((err?: Error | null) => (err ? reject(err) : resolve()));
    });

    const finalHeap = process.memoryUsage().heapUsed;
    const stats = fs.statSync(filePath);

    expect(stats.size).toBe(100 * 1024 * 1024);
    // Heap usage should NOT increase by 100 MB because chunks are drained incrementally
    const heapGrowthMB = (finalHeap - initialHeap) / (1024 * 1024);
    expect(heapGrowthMB).toBeLessThan(30); // Far less than 100 MB
  });

  it('4. 150 MB upload simulation: memory remains strictly bounded under max allowed size', async () => {
    const filePath = path.join(tmpDir, '150mb_sim.mp4');
    const ws = fs.createWriteStream(filePath, { highWaterMark: 64 * 1024 });

    const chunk = Buffer.alloc(64 * 1024, 0x42); // 64 KB chunk
    const iterations = 150 * 16; // 150 MB total (2400 * 64KB)

    const initialHeap = process.memoryUsage().heapUsed;

    for (let i = 0; i < iterations; i++) {
      await writeChunkWithBackpressure(ws, chunk);
    }

    await new Promise<void>((resolve, reject) => {
      ws.end((err?: Error | null) => (err ? reject(err) : resolve()));
    });

    const stats = fs.statSync(filePath);
    expect(stats.size).toBe(150 * 1024 * 1024);
    const finalHeap = process.memoryUsage().heapUsed;
    const heapGrowthMB = (finalHeap - initialHeap) / (1024 * 1024);
    expect(heapGrowthMB).toBeLessThan(40); // Memory is strictly bounded
  });

  it('5. Slow disk/write simulation: correctly awaits drain when write returns false', async () => {
    const filePath = path.join(tmpDir, 'slow_disk.mp4');
    // tiny highWaterMark to ensure write returns false
    const ws = fs.createWriteStream(filePath, { highWaterMark: 16 });

    let drainTriggered = false;
    ws.on('drain', () => {
      drainTriggered = true;
    });

    const bigChunk = Buffer.alloc(1024, 'X');
    await writeChunkWithBackpressure(ws, bigChunk);

    expect(drainTriggered).toBe(true);

    await new Promise<void>((resolve, reject) => {
      ws.end((err?: Error | null) => (err ? reject(err) : resolve()));
    });
  });

  it('6. Stream errors: rejects immediately if writeStream emits an error', async () => {
    const filePath = path.join(tmpDir, 'error_stream.bin');
    // highWaterMark: 1 ensures the very first write() returns false → enters drain wait immediately
    const ws = fs.createWriteStream(filePath, { highWaterMark: 1 });

    // Absorb any error events that fire after writeChunkWithBackpressure has already
    // rejected (to prevent "Unhandled 'error' event" process crash in later iterations)
    ws.on('error', () => {});

    // Open the fd before writing so we can emit an error while in drain wait
    await new Promise<void>((resolve) => ws.once('open', () => resolve()));

    // Start one write — with highWaterMark: 1 and a 64-byte chunk, write() returns false
    // immediately, so writeChunkWithBackpressure will be awaiting 'drain'/'error'/'close'
    const writePromise = writeChunkWithBackpressure(ws, Buffer.alloc(64, 'E'));

    // Emit error while the promise is waiting for drain
    ws.emit('error', new Error('Disk I/O error ENOSPC'));

    await expect(writePromise).rejects.toThrow('Disk I/O error ENOSPC');
    ws.destroy();
  });

  it('7. Client cancellation during upload: writeStream is destroyed and temp file cleaned up', async () => {
    const tempPath = path.join(tmpDir, 'cancelled_upload.tmp');
    const ws = fs.createWriteStream(tempPath, { highWaterMark: 64 });

    // Swallow any error events emitted after destruction to prevent unhandled error crash
    ws.on('error', () => {});

    let writeAborted = false;
    try {
      for (let i = 0; i < 50; i++) {
        await writeChunkWithBackpressure(ws, Buffer.alloc(128, 'C'));
        if (i === 5) {
          // Client cancels mid-upload: destroy writeStream
          ws.destroy(new Error('Upload aborted by user'));
        }
      }
    } catch (e: any) {
      writeAborted = true;
      expect(e.message).toMatch(/Upload aborted by user|Upload stream closed prematurely/);
    } finally {
      if (fs.existsSync(tempPath)) {
        fs.unlinkSync(tempPath);
      }
    }

    expect(writeAborted).toBe(true);
    expect(fs.existsSync(tempPath)).toBe(false);
  });

  it('8. Premature stream closure: rejects when stream closes before drain completes', async () => {
    const filePath = path.join(tmpDir, 'premature_close.bin');
    // highWaterMark: 1 guarantees write() returns false immediately → enters drain wait
    const ws = fs.createWriteStream(filePath, { highWaterMark: 1 });

    // Swallow errors emitted by destroy() to prevent unhandled error crash
    ws.on('error', () => {});

    // Wait for fd to be open so destroy() runs against a live stream
    await new Promise<void>((resolve) => ws.once('open', () => resolve()));

    // Start write — write() returns false immediately (1024 >> 1 byte highWaterMark),
    // so writeChunkWithBackpressure enters its drain-wait Promise
    const writePromise = writeChunkWithBackpressure(ws, Buffer.alloc(1024, 'P'));

    // Destroy while awaiting drain → emits 'close' → our onClose fires
    ws.destroy();

    // Accept either our message or Node's native "stream was destroyed" message —
    // both represent the same premature-closure condition.
    await expect(writePromise).rejects.toThrow(/closed prematurely|stream was destroyed/);
  });

  it('9. Multiple concurrent uploads: 4 directional streams execute concurrently with bounded memory', async () => {
    const directions = ['north', 'south', 'east', 'west'];
    const initialHeap = process.memoryUsage().heapUsed;

    const tasks = directions.map(async (dir) => {
      const p = path.join(tmpDir, `${dir}.mp4`);
      const ws = fs.createWriteStream(p, { highWaterMark: 32 * 1024 });
      const chunk = Buffer.alloc(32 * 1024, dir.charCodeAt(0));

      for (let i = 0; i < 200; i++) { // ~6.4 MB each = ~25.6 MB total
        await writeChunkWithBackpressure(ws, chunk);
      }

      await new Promise<void>((resolve, reject) => {
        ws.end((err?: Error | null) => (err ? reject(err) : resolve()));
      });

      const stats = fs.statSync(p);
      expect(stats.size).toBe(200 * 32 * 1024);
    });

    await Promise.all(tasks);

    const finalHeap = process.memoryUsage().heapUsed;
    const growthMB = (finalHeap - initialHeap) / (1024 * 1024);
    expect(growthMB).toBeLessThan(25);
  });
});
