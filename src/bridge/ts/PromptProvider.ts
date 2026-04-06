import { spawn, ChildProcess } from "child_process";
import { createInterface, Interface } from "readline";

// ── Types ──────────────────────────────────────────────────────────────────

/** Request / response IDs are sequential numbers. */
type RpcId = number;

interface PendingCall {
  resolve: (value: unknown) => void;
  reject: (reason: Error) => void;
}

/** Parameters for the render_graph RPC method. */
export interface RenderGraphParams {
  template_names: string[];
  context: Record<string, unknown>;
  agent_role?: string;
}

/** Response from the Python render_graph handler. */
export interface RenderGraphResult {
  system_prompt: string;
  memory_blocks_used: number;
}

/** Parameters for the retrieve RPC method. */
export interface RetrieveParams {
  query: string;
  agent_role: string;
  k?: number;
}

/** Response from the Python retrieve handler. */
export interface RetrieveResult {
  memories: unknown[];
}

// ── PromptProvider ─────────────────────────────────────────────────────────

/**
 * TypeScript side of the Python ↔ TS stdio JSON-RPC bridge.
 *
 * Spawns `python -m src.bridge.server` as a child process and communicates
 * over stdin/stdout with one JSON object per line.
 */
export class PromptProvider {
  private process: ChildProcess;
  private rl: Interface;
  private nextId = 1;
  private pending = new Map<RpcId, PendingCall>();

  constructor(pythonPath = "python") {
    this.process = spawn(pythonPath, ["-m", "src.bridge.server"], {
      stdio: ["pipe", "pipe", "pipe"],
      cwd: process.cwd(),
    });

    this.rl = createInterface({ input: this.process.stdout!, terminal: false });
    this.rl.on("line", (line) => this.onResponse(line));

    this.process.stderr?.on("data", (data: Buffer) => {
      console.error(`[Python Bridge stderr]: ${data.toString().trim()}`);
    });

    this.process.on("error", (err) => {
      console.error(`[Python Bridge] spawn error: ${err.message}`);
    });

    this.process.on("exit", (code) => {
      // Reject every outstanding call
      for (const [id, { reject }] of this.pending) {
        reject(new Error(`Python process exited (code ${code})`));
        this.pending.delete(id);
      }
    });
  }

  // ── Public API ───────────────────────────────────────────────────────

  /**
   * Ask the Python PromptOS to render a set of Jinja2 templates into
   * a single assembled system prompt string.
   */
  async renderGraph(params: RenderGraphParams): Promise<RenderGraphResult> {
    const result = await this.call("render_graph", params);
    return result as RenderGraphResult;
  }

  /**
   * Ask the Python Memory Fabric to retrieve ranked memories for an agent.
   */
  async retrieve(params: RetrieveParams): Promise<RetrieveResult> {
    const result = await this.call("retrieve", params);
    return result as RetrieveResult;
  }

  /** Health check — returns { status, version }. */
  async ping(): Promise<{ status: string; version: string }> {
    const result = await this.call("ping", {});
    return result as { status: string; version: string };
  }

  /** Shut down the Python child process. */
  terminate(): void {
    this.rl.close();
    this.process.kill();
  }

  // ── Internals ────────────────────────────────────────────────────────

  private call(method: string, params: Record<string, unknown>): Promise<unknown> {
    const id = this.nextId++;
    const payload = JSON.stringify({ id, method, params }) + "\n";

    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.process.stdin!.write(payload);
    });
  }

  private onResponse(line: string): void {
    let data: { id?: number; error?: string; result?: unknown };
    try {
      data = JSON.parse(line);
    } catch {
      console.error(`[Python Bridge] non-JSON line: ${line}`);
      return;
    }

    const id = data.id;
    if (id == null) return;

    const entry = this.pending.get(id);
    if (!entry) return;
    this.pending.delete(id);

    if (data.error) {
      entry.reject(new Error(data.error));
    } else {
      entry.resolve(data.result ?? data);
    }
  }
}
