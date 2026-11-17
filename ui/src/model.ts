export type Span = {
  id: string;
  parent_id: string | null;
  service: string;
  operation: string;
  start_ms: number;
  duration_ms: number;
  status: "ok" | "error";
  http_status: number | null;
  attributes: Record<string, string | number | boolean>;
};
export type Execution = {
  id: string;
  name: string;
  version: string;
  spans: Span[];
  fixture: null | {
    inventory_status: number;
    payment_status: number;
    captured_checkout_status: number;
    quantity: number;
  };
};
export type Summary = {
  id: string;
  name: string;
  version: string;
  outcome: string;
  span_count: number;
  created_at: string;
};
export type Job = {
  id: string;
  execution_id: string;
  status: string;
  attempts: number;
  created_at: string;
  result: null | {
    passed?: boolean;
    observed_status?: number;
    expected_status?: number;
    matches_capture?: boolean;
    elapsed_ms?: number;
    error?: string;
    scope?: string;
    calls?: { service: string; path: string; status: number }[];
  };
};
export type Change = {
  service: string;
  operation: string;
  occurrence: number;
  left_span: string | null;
  right_span: string | null;
  change: string;
  duration_delta_ms: number | null;
  left_status: number | null;
  right_status: number | null;
};
export function orderedSpans(spans: Span[]): Span[] {
  const children = new Map<string | null, Span[]>();
  for (const s of spans) {
    const group = children.get(s.parent_id) || [];
    group.push(s);
    children.set(s.parent_id, group);
  }
  const output: Span[] = [];
  const seen = new Set<string>();
  function visit(parent: string | null) {
    for (const s of (children.get(parent) || []).sort(
      (a, b) => a.start_ms - b.start_ms || a.id.localeCompare(b.id),
    )) {
      if (seen.has(s.id)) continue;
      seen.add(s.id);
      output.push(s);
      visit(s.id);
    }
  }
  visit(null);
  return output;
}
export function depth(span: Span, spans: Span[]): number {
  const map = new Map(spans.map((s) => [s.id, s]));
  const seen = new Set<string>();
  let n = 0,
    p = span.parent_id;
  while (p && map.has(p) && !seen.has(p)) {
    seen.add(p);
    n++;
    p = map.get(p)!.parent_id;
  }
  return n;
}
export function serviceGraph(spans: Span[]) {
  const map = new Map(spans.map((s) => [s.id, s.service]));
  const services = [...new Set(spans.map((s) => s.service))];
  const edges = [
    ...new Set(
      spans
        .filter((s) => s.parent_id && map.get(s.parent_id) !== s.service)
        .map((s) => `${map.get(s.parent_id!)} → ${s.service}`),
    ),
  ];
  return { services, edges };
}
