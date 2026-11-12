// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * FakeWebSocket — a WebSocket stand-in for tests. Install it with
 * `vi.stubGlobal("WebSocket", FakeWebSocket)`; drive it with `open()`, `receive()` and `drop()`.
 */

export class FakeWebSocket {
  static instances: FakeWebSocket[] = []
  static readonly CONNECTING = 0
  static readonly OPEN = 1
  static readonly CLOSING = 2
  static readonly CLOSED = 3

  readonly url: string
  readonly protocols: string[]
  readyState = 0
  sent: string[] = []
  closedWith: number | undefined
  onopen: ((event: unknown) => void) | null = null
  onmessage: ((event: { data: string }) => void) | null = null
  onclose: ((event: { code: number }) => void) | null = null
  onerror: ((event: unknown) => void) | null = null

  constructor(url: string, protocols: string | string[] = []) {
    this.url = url
    this.protocols = Array.isArray(protocols) ? protocols : [protocols]
    FakeWebSocket.instances.push(this)
  }

  static reset(): void {
    FakeWebSocket.instances = []
  }

  static last(): FakeWebSocket {
    const ws = FakeWebSocket.instances.at(-1)
    if (!ws) throw new Error("no WebSocket was opened")
    return ws
  }

  send(text: string): void {
    if (this.readyState !== 1) throw new Error("send before open")
    this.sent.push(text)
  }

  close(code = 1000): void {
    this.readyState = 3
    this.closedWith = code
  }

  // -- test controls ---------------------------------------------------------

  open(): void {
    this.readyState = 1
    this.onopen?.({})
  }

  receive(frame: unknown): void {
    this.onmessage?.({ data: typeof frame === "string" ? frame : JSON.stringify(frame) })
  }

  /** The server or the network closed the connection. */
  drop(code = 1006): void {
    this.readyState = 3
    this.onclose?.({ code })
  }

  messages(): Record<string, unknown>[] {
    return this.sent.map((text) => JSON.parse(text))
  }

  ofType(type: string): Record<string, unknown>[] {
    return this.messages().filter((m) => m.type === type)
  }
}
