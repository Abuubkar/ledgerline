import "@testing-library/jest-dom";
import { clearImmediate, setImmediate } from "node:timers";

// jsdom has no setImmediate, and MSW's request interception schedules work with it ("fetch failed" otherwise).
Object.assign(globalThis, { setImmediate, clearImmediate });
