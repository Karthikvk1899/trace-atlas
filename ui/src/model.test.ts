import { expect, test } from "vitest";
import { orderedSpans, depth, serviceGraph, type Span } from "./model";
const root: Span = {
  id: "r",
  parent_id: null,
  service: "api",
  operation: "GET /",
  start_ms: 0,
  duration_ms: 10,
  status: "ok",
  http_status: 200,
  attributes: {},
};
const child: Span = {
  ...root,
  id: "c",
  parent_id: "r",
  service: "db",
  start_ms: 1,
};
test("unordered evidence renders parents before children", () => {
  expect(orderedSpans([child, root]).map((x) => x.id)).toEqual(["r", "c"]);
  expect(depth(child, [child, root])).toBe(1);
});
test("service edges derive from parent ids, not time order", () => {
  expect(serviceGraph([child, root]).edges).toEqual(["api → db"]);
});
test("cycles cannot hang the UI", () => {
  expect(
    depth({ ...child, parent_id: "c" }, [{ ...child, parent_id: "c" }]),
  ).toBe(1);
  expect(orderedSpans([{ ...child, parent_id: "c" }])).toEqual([]);
});
