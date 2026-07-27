/** Schema of /api/graph/data — emitted by curiosity-engine's wiki_render.py. */
export type GraphData = {
  workspace: string;
  generated_at: string;
  palette: Record<string, string>;
  nodes: Array<{ id: string; path: string; type: string; title: string; degree: number }>;
  edges: Array<{ source: string; target: string; type: string }>;
  pages: Record<
    string,
    {
      id: string;
      title: string;
      type: string;
      path: string;
      properties: Record<string, unknown>;
      body_html: string;
    }
  >;
};
