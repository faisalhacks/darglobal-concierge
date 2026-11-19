// Minimal Server-Sent-Events parser for a fetch() ReadableStream (POST cannot use EventSource).
export interface SSEFrame { event: string; data: string }

export function createSSEParser(onFrame: (f: SSEFrame) => void) {
  let buf = "";
  const flush = (block: string) => {
    let event = "message";
    const data: string[] = [];
    for (const raw of block.split("\n")) {
      const line = raw.endsWith("\r") ? raw.slice(0, -1) : raw;
      if (!line || line.startsWith(":")) continue;
      const i = line.indexOf(":");
      const field = i === -1 ? line : line.slice(0, i);
      let value = i === -1 ? "" : line.slice(i + 1);
      if (value.startsWith(" ")) value = value.slice(1);
      if (field === "event") event = value;
      else if (field === "data") data.push(value);
    }
    if (data.length) onFrame({ event, data: data.join("\n") });
  };
  return {
    push(chunk: string) {
      buf += chunk.replace(/\r\n/g, "\n");
      let idx: number;
      while ((idx = buf.indexOf("\n\n")) !== -1) {
        const block = buf.slice(0, idx);
        buf = buf.slice(idx + 2);
        flush(block);
      }
    },
    end() { if (buf.trim()) flush(buf); buf = ""; },
  };
}

export async function readSSE(body: ReadableStream<Uint8Array>, onFrame: (f: SSEFrame) => void) {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  const parser = createSSEParser(onFrame);
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    parser.push(decoder.decode(value, { stream: true }));
  }
  parser.push(decoder.decode());
  parser.end();
}
