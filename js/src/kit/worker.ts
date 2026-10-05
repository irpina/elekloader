// SPDX-License-Identifier: GPL-3.0-or-later
// The kit's builder worker. A site starts it as a module worker from its own origin (worker.js beside the engine's
// files, or this file through a bundler) and talks to it in the messages of protocol.ts, usually through client.ts.
//
// It keeps to the site it was started from: before anything loads, fetch and XMLHttpRequest refuse other origins,
// and WebSocket, EventSource, WebTransport and RTCPeerConnection are gone. A worker takes its Content Security Policy
// from its own response headers, which a static host may not send, so the worker enforces this itself. The owner's
// files stay in this worker's memory and go nowhere.
import { createService } from './serve.ts'
import type { Answer, Call } from './protocol.ts'

const scope = self as unknown as Record<string, unknown> & { location: Location; fetch: typeof fetch }
const SITE = scope.location.origin
const sameSite = (url: string) => new URL(url, scope.location.href).origin === SITE
const siteFetch = scope.fetch.bind(self)
scope.fetch = (input: RequestInfo | URL, init?: RequestInit) => {
  const url = input instanceof Request ? input.url : String(input)
  return sameSite(url) ? siteFetch(input, init) : Promise.reject(new TypeError('Refused: ' + url + ' is not on this site.'))
}
for (const key of ['XMLHttpRequest', 'WebSocket', 'WebSocketStream', 'EventSource', 'WebTransport', 'RTCPeerConnection']) if (key in scope) scope[key] = undefined

const handle = createService(async url => {
  if (!sameSite(url)) throw new Error('The builder loads only from this site: ' + url)
  const response = await scope.fetch(url)
  if (!response.ok) throw new Error(url.split('/').pop() + ': ' + response.status)
  return new Uint8Array(await response.arrayBuffer())
})

const post = (answer: Answer, transfer: Transferable[] = []) => (self as unknown as Worker).postMessage(answer, transfer)

self.onmessage = async (event: MessageEvent<Call>) => {
  const { id } = event.data
  try {
    const result = await handle(event.data, line => post({ id, log: line }))
    const files = (result as { files?: { data?: unknown }[] } | null)?.files ?? []
    post({ id, ok: true, result }, files.map(f => f.data).filter((d): d is ArrayBuffer => d instanceof ArrayBuffer))
  } catch (error) {
    post({ id, ok: false, error: error instanceof Error ? error.message : String(error) })
  }
}
