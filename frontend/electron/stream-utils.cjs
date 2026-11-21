/*
 * Urban Flow - Adaptive Traffic Signal System
 * Copyright (c) 2026 Harsh Aggarwal <aggarwalharsh663@gmail.com>. All rights reserved.
 *
 * Original Author & Sole Intellectual Property Owner: Harsh Aggarwal
 * Any additions, modifications, or contributed files to this project automatically
 * and irrevocably vest all copyright and intellectual property rights solely in Harsh Aggarwal.
 */

const { once } = require('events');

/**
 * Write a buffer chunk to a writable stream honoring stream backpressure.
 * When the internal stream buffer is full (write() returns false), pauses reading
 * and awaits the 'drain' event or catches premature errors/closure.
 *
 * If the stream is already destroyed or closed on entry, rejects immediately.
 * Registers drain/close/error listeners BEFORE calling write() so that any
 * synchronous error emission from write() on a destroyed stream is captured.
 *
 * @param {import('stream').Writable} writeStream
 * @param {Buffer | Uint8Array} chunk
 * @returns {Promise<void>}
 */
function writeChunkWithBackpressure(writeStream, chunk) {
  if (writeStream.destroyed || writeStream.closed) {
    return Promise.reject(new Error('Upload stream closed prematurely before drain.'));
  }

  // Register listeners BEFORE write() so that if the stream is destroyed
  // between our guard check and write() — causing an immediate 'error' or
  // 'close' event — we capture it rather than leaving it unhandled.
  return new Promise((resolve, reject) => {
    function onDrain() {
      cleanup();
      resolve();
    }
    function onClose() {
      cleanup();
      reject(new Error('Upload stream closed prematurely before drain.'));
    }
    function onError(err) {
      cleanup();
      reject(err);
    }

    function cleanup() {
      writeStream.removeListener('drain', onDrain);
      writeStream.removeListener('close', onClose);
      writeStream.removeListener('error', onError);
    }

    writeStream.once('drain', onDrain);
    writeStream.once('close', onClose);
    writeStream.once('error', onError);

    let needsDrain;
    try {
      needsDrain = !writeStream.write(chunk);
    } catch (syncErr) {
      // write() threw synchronously (some Node versions do this on destroyed streams)
      cleanup();
      reject(new Error('Upload stream closed prematurely before drain.'));
      return;
    }

    // If write() returned true the buffer accepted the chunk — no drain needed
    if (!needsDrain) {
      cleanup();
      resolve();
    }
    // else: needsDrain === true → wait for drain/close/error via registered listeners
  });
}

module.exports = {
  writeChunkWithBackpressure,
};
