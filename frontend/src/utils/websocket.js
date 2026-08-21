import { Client } from '@stomp/stompjs'

import { useTokenStore } from '@/stores/token.js'

let stompClient = null
let connected = false
let disconnecting = null
const listeners = new Map()

const websocketUrl = () => {
  if (import.meta.env.VITE_WS_URL) return import.meta.env.VITE_WS_URL
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${protocol}//${window.location.host}/ws`
}

const activateSubscriptions = () => {
  for (const [callback, record] of listeners) {
    record.subscription?.unsubscribe()
    record.subscription = stompClient.subscribe(record.destination, message => {
      try {
        callback(JSON.parse(message.body))
      } catch {
        // 非 JSON 消息保留为原始文本，避免整条订阅链路中断。
        callback({ content: message.body })
      }
    })
  }
}

export function connect(onConnected) {
  if (stompClient?.active) return
  const tokenStore = useTokenStore()
  const token = tokenStore.token
  // WebSocket 只承载聊天和通知，不是知识助手的依赖。没有 Java JWT 时不建立
  // STOMP 连接，避免无关的鉴权 ERROR 干扰 Agent QA 页面。
  if (!token) return
  stompClient = new Client({
    brokerURL: websocketUrl(),
    connectHeaders: { Authorization: token },
    reconnectDelay: 3000,
    heartbeatIncoming: 10000,
    heartbeatOutgoing: 10000,
    debug: import.meta.env.DEV ? message => console.debug('[STOMP]', message) : () => {},
    onConnect: () => {
      connected = true
      activateSubscriptions()
      if (typeof onConnected === 'function') onConnected()
    },
    onWebSocketClose: () => { connected = false },
    onStompError: frame => {
      connected = false
      // Spring 的 message 通常只是 clientInboundChannel 包装信息，body 才包含底层原因。
      // ERROR 帧后服务端会关闭连接，因此停用自动重连，避免控制台每 3 秒重复报错。
      const detail = frame.body || frame.headers?.message || '未知 STOMP 错误'
      console.warn('STOMP connection rejected:', detail)
      void stompClient?.deactivate()
    }
  })
  stompClient.activate()
}

export function subscribe(destination, callback) {
  const current = listeners.get(callback)
  current?.subscription?.unsubscribe()
  listeners.set(callback, { destination, subscription: null })
  if (connected) activateSubscriptions()
}

export function unsubscribe(callback) {
  const record = listeners.get(callback)
  record?.subscription?.unsubscribe()
  listeners.delete(callback)
}

export function sendMsg(destination, message) {
  if (!connected || !stompClient) throw new Error('WebSocket 尚未连接')
  stompClient.publish({ destination, body: JSON.stringify(message) })
}

export function disconnect() {
  if (disconnecting) return disconnecting

  const client = stompClient
  stompClient = null
  listeners.clear()
  connected = false
  disconnecting = (async () => {
    if (client) await client.deactivate()
  })().finally(() => {
    disconnecting = null
  })
  return disconnecting
}
