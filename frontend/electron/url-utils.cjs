/*
 * Urban Flow - Adaptive Traffic Signal System
 * Copyright (c) 2026 Harsh Aggarwal <aggarwalharsh663@gmail.com>. All rights reserved.
 *
 * Original Author & Sole Intellectual Property Owner: Harsh Aggarwal
 * Any additions, modifications, or contributed files to this project automatically
 * and irrevocably vest all copyright and intellectual property rights solely in Harsh Aggarwal.
 */

'use strict';

/**
 * Explicit trusted external domains required for Urban Flow documentation,
 * source code repository, and core dependency references.
 * Subdomains of these entries (e.g. docs.ultralytics.com, docs.opencv.org) are permitted.
 */
const TRUSTED_EXTERNAL_DOMAINS = Object.freeze([
  'github.com',
  'ultralytics.com',
  'opencv.org',
  'python.org',
  'fastapi.tiangolo.com',
  'electronjs.org',
]);

/**
 * Check if a hostname exactly matches an allowed domain or is a valid subdomain of it.
 * Prevents domain confusion attacks such as:
 *   - trusted-domain.com.evil.com (not a subdomain of trusted-domain.com)
 *   - evil-trusted-domain.com (not a subdomain of trusted-domain.com)
 *
 * @param {string} hostname
 * @param {string} allowedDomain
 * @returns {boolean}
 */
function isMatchingDomain(hostname, allowedDomain) {
  const normHost = hostname.toLowerCase();
  const normAllowed = allowedDomain.toLowerCase();
  return normHost === normAllowed || normHost.endsWith('.' + normAllowed);
}

/**
 * Validate an external URL before opening in external browser or application.
 *
 * Requirements enforced:
 * - String input only, non-empty, max 2048 characters
 * - No control characters or null bytes
 * - Only 'http:' and 'https:' protocols (rejects javascript:, file:, data:, blob:, custom:)
 * - Rejects URLs containing credentials (username/password)
 * - Rejects URLs with unexpected/disallowed ports (only standard 80 for http, 443 for https, or default)
 * - Rejects internationalized domain names (IDN / punycode xn--) to prevent homograph attacks
 * - Rejects hostnames containing invalid characters (spaces, backslashes)
 * - Differentiates between explicitly trusted domains and untrusted domains
 *
 * @param {string} rawUrl
 * @param {readonly string[] | null} [customTrustedDomains]
 * @returns {{
 *   valid: boolean;
 *   isTrusted: boolean;
 *   url?: string;
 *   hostname?: string;
 *   protocol?: string;
 *   reason: string;
 * }}
 */
function validateExternalUrl(rawUrl, customTrustedDomains = null) {
  if (typeof rawUrl !== 'string') {
    return { valid: false, isTrusted: false, reason: 'URL must be a string.' };
  }

  const trimmed = rawUrl.trim();
  if (!trimmed) {
    return { valid: false, isTrusted: false, reason: 'URL cannot be empty.' };
  }

  if (trimmed.length > 2048) {
    return { valid: false, isTrusted: false, reason: 'URL exceeds maximum length of 2048 characters.' };
  }

  // Reject control characters (0x00 - 0x1F, 0x7F)
  if (/[\x00-\x1f\x7f]/.test(trimmed)) {
    return { valid: false, isTrusted: false, reason: 'URL contains invalid control characters.' };
  }

  let parsed;
  try {
    parsed = new URL(trimmed);
  } catch {
    return { valid: false, isTrusted: false, reason: 'Malformed URL: unable to parse.' };
  }

  // Protocol check: only explicitly approved http: and https:
  const protocol = parsed.protocol.toLowerCase();
  if (protocol !== 'http:' && protocol !== 'https:') {
    return { valid: false, isTrusted: false, reason: `Disallowed protocol: ${protocol}` };
  }

  // Credentials check: reject any userinfo/credentials (prevents trusted.com@evil.com confusion)
  if (parsed.username || parsed.password) {
    return { valid: false, isTrusted: false, reason: 'URL contains unexpected credentials.' };
  }

  // Port check: reject unexpected ports
  const port = parsed.port;
  if (port !== '') {
    if (protocol === 'http:' && port !== '80') {
      return { valid: false, isTrusted: false, reason: `Unexpected port ${port} for http URL.` };
    }
    if (protocol === 'https:' && port !== '443') {
      return { valid: false, isTrusted: false, reason: `Unexpected port ${port} for https URL.` };
    }
  }

  // Hostname checks
  const hostname = parsed.hostname.toLowerCase();
  if (!hostname) {
    return { valid: false, isTrusted: false, reason: 'URL has an empty hostname.' };
  }

  // Internationalized Domain Name (IDN) / punycode check to prevent homoglyph attacks
  if (hostname.startsWith('xn--') || hostname.includes('.xn--')) {
    return { valid: false, isTrusted: false, reason: 'Internationalized domain names (punycode) are not permitted.' };
  }

  // Hostname character hygiene
  if (/[\s\\]/.test(hostname)) {
    return { valid: false, isTrusted: false, reason: 'Hostname contains invalid characters.' };
  }

  // Trusted domain check
  const trustedList = customTrustedDomains || TRUSTED_EXTERNAL_DOMAINS;
  const isTrusted = trustedList.some((allowed) => isMatchingDomain(hostname, allowed));

  return {
    valid: true,
    isTrusted,
    url: parsed.href,
    hostname,
    protocol,
    reason: isTrusted ? 'Trusted domain' : 'Untrusted external domain (requires user confirmation)',
  };
}

/**
 * Handle opening an external URL securely.
 *
 * Behavior:
 * 1. Validates the URL via validateExternalUrl(). If invalid, logs and rejects immediately.
 * 2. If valid and explicitly trusted: opens directly in the external browser via shell.openExternal().
 * 3. If valid and untrusted: displays an Electron confirmation dialog showing the destination hostname.
 *    - If user confirms: opens in the external browser.
 *    - If user cancels: does not open.
 *
 * @param {string} rawUrl
 * @param {{
 *   parentWindow?: any;
 *   dialogFn?: (windowOrOpts: any, maybeOpts?: any) => Promise<{ response: number } | number>;
 *   shellOpenFn?: (url: string) => Promise<void>;
 *   customTrustedDomains?: readonly string[];
 *   logger?: (msg: string) => void;
 * }} [options]
 * @returns {Promise<{
 *   opened: boolean;
 *   isTrusted?: boolean;
 *   url?: string;
 *   reason?: string;
 *   userConfirmed?: boolean;
 *   error?: string;
 * }>}
 */
async function openExternalUrl(rawUrl, options = {}) {
  const {
    parentWindow = null,
    dialogFn = null,
    shellOpenFn = null,
    customTrustedDomains = null,
    logger = console.log,
  } = options;

  let showMessageBox = dialogFn;
  let openExternal = shellOpenFn;

  // If running inside Electron, resolve dialog and shell dynamically if not provided
  if (!showMessageBox || !openExternal) {
    try {
      if (typeof process !== 'undefined' && process.versions && process.versions.electron) {
        const electron = require('electron');
        if (!showMessageBox && electron.dialog) {
          showMessageBox = electron.dialog.showMessageBox.bind(electron.dialog);
        }
        if (!openExternal && electron.shell) {
          openExternal = electron.shell.openExternal.bind(electron.shell);
        }
      }
    } catch {}
  }

  const validation = validateExternalUrl(rawUrl, customTrustedDomains);
  if (!validation.valid) {
    logger(`[Security] Blocked external URL: "${rawUrl}" - ${validation.reason}`);
    return { opened: false, isTrusted: false, reason: validation.reason };
  }

  // Path 1: Trusted domain - open immediately without confirmation
  if (validation.isTrusted) {
    if (!openExternal) {
      logger(`[Navigation] shell.openExternal unavailable for trusted URL: ${validation.url}`);
      return { opened: false, isTrusted: true, reason: 'External browser launcher unavailable.' };
    }
    try {
      await openExternal(validation.url);
      logger(`[Navigation] Opened trusted external URL: ${validation.url}`);
      return { opened: true, isTrusted: true, url: validation.url };
    } catch (err) {
      const errMsg = err && err.message ? err.message : String(err);
      logger(`[Navigation] Failed to open trusted external URL: ${validation.url} - ${errMsg}`);
      return { opened: false, isTrusted: true, error: errMsg };
    }
  }

  // Path 2: Untrusted HTTP/HTTPS domain - prompt user for confirmation
  if (!showMessageBox) {
    logger(`[Security] Confirmation dialog unavailable. Blocked untrusted URL: ${validation.url}`);
    return { opened: false, isTrusted: false, reason: 'Confirmation dialog unavailable.' };
  }

  const dialogOpts = {
    type: 'question',
    buttons: ['Open Link', 'Cancel'],
    defaultId: 1, // Default to Cancel
    cancelId: 1,  // Escape / close triggers Cancel
    title: 'External Link Confirmation',
    message: 'Open external link in your default browser?',
    detail: `Destination:\n${validation.url}\n\nHost: ${validation.hostname}\n\nThis website is outside of Urban Flow. Only open links from sources you trust.`,
    noLink: true,
  };

  try {
    let result;
    if (parentWindow && typeof parentWindow.isDestroyed === 'function' && !parentWindow.isDestroyed()) {
      result = await showMessageBox(parentWindow, dialogOpts);
    } else {
      result = await showMessageBox(dialogOpts);
    }

    const responseIndex = typeof result === 'object' && result !== null && 'response' in result
      ? result.response
      : result;

    if (responseIndex === 0) {
      if (!openExternal) {
        logger(`[Navigation] shell.openExternal unavailable for: ${validation.url}`);
        return { opened: false, isTrusted: false, userConfirmed: true, reason: 'External browser launcher unavailable.' };
      }
      try {
        await openExternal(validation.url);
        logger(`[Navigation] User approved and opened external URL: ${validation.url}`);
        return { opened: true, isTrusted: false, userConfirmed: true, url: validation.url };
      } catch (openErr) {
        const errMsg = openErr && openErr.message ? openErr.message : String(openErr);
        logger(`[Navigation] Error opening external URL after approval: ${errMsg}`);
        return { opened: false, isTrusted: false, userConfirmed: true, error: errMsg };
      }
    } else {
      logger(`[Navigation] User cancelled opening external URL: ${validation.url}`);
      return { opened: false, isTrusted: false, userConfirmed: false, reason: 'User cancelled confirmation.' };
    }
  } catch (dialogErr) {
    const errMsg = dialogErr && dialogErr.message ? dialogErr.message : String(dialogErr);
    logger(`[Security] Confirmation dialog error: ${errMsg}`);
    return { opened: false, isTrusted: false, error: errMsg };
  }
}

module.exports = {
  TRUSTED_EXTERNAL_DOMAINS,
  isMatchingDomain,
  validateExternalUrl,
  openExternalUrl,
};
