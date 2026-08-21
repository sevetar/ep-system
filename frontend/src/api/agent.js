import agentRequest from '@/utils/agentRequest.js'

const principalConfig = (tenantId, principalId) => ({
  headers: {
    'X-Tenant-Id': tenantId,
    ...(principalId ? { 'X-Principal-Id': principalId } : {})
  }
})

export const getAgentReadiness = () => agentRequest.get('/health/ready')

export const executeAssistant = (
  message, threadId, tenantId = 'public', principalId = ''
) => agentRequest.post('/v1/assistant/execute', {
  message,
  thread_id: threadId,
  scope: { tenant_id: tenantId }
}, principalConfig(tenantId, principalId))

export const queryKnowledge = (query, tenantId = 'public') => agentRequest.post('/v1/qa/query', {
  query,
  scope: { tenant_id: tenantId },
  options: {}
}, principalConfig(tenantId))

export const startDispatch = (payload, tenantId = 'default') => (
  agentRequest.post('/v1/dispatch/start', payload, principalConfig(tenantId))
)

export const resumeDispatch = (threadId, approval, tenantId = 'default', reviewerId = '') => (
  agentRequest.post(
    `/v1/dispatch/${encodeURIComponent(threadId)}/resume`,
    approval,
    principalConfig(tenantId, reviewerId)
  )
)

export const retryDispatch = (threadId, tenantId = 'default') => (
  agentRequest.post(
    `/v1/dispatch/${encodeURIComponent(threadId)}/retry`,
    null,
    principalConfig(tenantId)
  )
)

export const getDispatchStatus = (threadId, tenantId = 'default') => (
  agentRequest.get(
    `/v1/dispatch/${encodeURIComponent(threadId)}/status`,
    principalConfig(tenantId)
  )
)

export const getDispatchHistory = (threadId, tenantId = 'default') => (
  agentRequest.get(
    `/v1/dispatch/${encodeURIComponent(threadId)}/history`,
    principalConfig(tenantId)
  )
)
