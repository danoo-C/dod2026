// Before every test file. jsdom has <video> but doesn't implement playing it:
// play(), pause() and load() only log "Not implemented". Tests that care spy
// on them; the rest just need them quiet.
import { beforeEach } from "vitest";

beforeEach(() => {
  HTMLMediaElement.prototype.play = function play() {
    Object.defineProperty(this, "paused", { configurable: true, value: false });
    return Promise.resolve();
  };
  HTMLMediaElement.prototype.pause = function pause() {
    Object.defineProperty(this, "paused", { configurable: true, value: true });
  };
  HTMLMediaElement.prototype.load = function load() {};
});
