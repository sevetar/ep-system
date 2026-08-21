<script setup>
import { CircleCheck, Clock, Document, MagicStick, Refresh, Search } from '@element-plus/icons-vue'
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'

import {
  executeAssistant,
  getDispatchHistory,
  getDispatchStatus,
  getAgentReadiness,
  queryKnowledge,
  resumeDispatch,
  retryDispatch,
  startDispatch
} from '@/api/agent.js'
import { triggerAutoDispatch } from '@/api/device.js'
import useUserInfoStore from '@/stores/userInfo.js'

const userStore = useUserInfoStore()
const activeTab = ref('assistant')
const assistantLoading = ref(false)
const assistantDispatchLoading = ref(false)
const assistantMessage = ref('调查设备 DEV-1003 的异常原因')
const assistantTenant = ref('public')
const assistantThreadId = ref(`assistant-ui-${Date.now().toString(36)}`)
const assistantResult = ref(null)
const asking = ref(false)
const question = ref('Java 派单成功需要满足哪些最终核验条件？')
const knowledgeTenant = ref('public')
const answer = ref(null)
const readiness = ref(null)
const readinessLoading = ref(false)

const dispatchLoading = ref(false)
const dispatchResult = ref(null)
const manualIdempotencyKey = ref('')
const manualIdempotencyOrder = ref('')
const history = ref([])
const lookupThreadId = ref('')
const dispatchForm = ref({
  work_order_id: '',
  tenant_id: 'default',
  event_id: '',
  dispatch_id: '',
  trace_id: ''
})
const approval = ref({ reviewer_id: '', worker_id: '', reason: '' })

const isAdmin = computed(() => Array.isArray(userStore.role) && userStore.role.includes(1))
const candidates = computed(() => dispatchResult.value?.decision?.candidates || [])
const needsApproval = computed(() => dispatchResult.value?.status === 'awaiting_approval')
const agentReady = computed(() => readiness.value?.status === 'ok')
const readinessLabel = computed(() => {
  if (readinessLoading.value) return 'Agent service checking'
  if (agentReady.value) return 'Agent service connected'
  return readiness.value ? 'Agent dependencies degraded' : 'Agent service unavailable'
})
const assistantCitations = computed(() => assistantResult.value?.qa?.citations || [])
const assistantEvidenceRefs = computed(() => (
  assistantResult.value?.investigation?.evidence_refs
  || assistantResult.value?.planning?.artifacts?.flatMap(item => item.evidence_refs || [])
  || []
))

const checkReadiness = async ({ notify = false } = {}) => {
  readinessLoading.value = true
  try {
    readiness.value = (await getAgentReadiness()).data
    if (notify) {
      if (readiness.value?.status === 'ok') {
        ElMessage.success('Agent 服务及依赖均正常')
      } else {
        const degradedDependencies = Object.entries(readiness.value?.dependencies || {})
          .filter(([, status]) => status !== 'ok')
          .map(([name]) => name)
        const detail = degradedDependencies.length
          ? `：${degradedDependencies.join('、')}`
          : ''
        ElMessage.warning(`Agent 依赖存在异常${detail}`)
      }
    }
  } catch {
    readiness.value = null
    // 请求拦截器会统一显示具体的网络或服务错误。
  } finally {
    readinessLoading.value = false
  }
}

onMounted(checkReadiness)

const ask = async () => {
  if (!question.value.trim()) return ElMessage.warning('请输入问题')
  asking.value = true
  try {
    answer.value = (await queryKnowledge(
      question.value.trim(), knowledgeTenant.value.trim() || 'public'
    )).data
  } finally {
    asking.value = false
  }
}

const runAssistant = async () => {
  if (!assistantMessage.value.trim()) return ElMessage.warning('请输入请求')
  assistantLoading.value = true
  try {
    assistantResult.value = (await executeAssistant(
      assistantMessage.value.trim(),
      assistantThreadId.value,
      assistantTenant.value,
      String(userStore.info?.id || userStore.info?.userId || '')
    )).data
  } finally {
    assistantLoading.value = false
  }
}

const confirmAssistantDispatch = async () => {
  const workOrderId = assistantResult.value?.next_action?.continuation_id
  if (!workOrderId) return ElMessage.warning('未找到待派单工单')
  if (!isAdmin.value) return ElMessage.warning('仅管理员可以确认自动派单')
  assistantDispatchLoading.value = true
  try {
    const idempotencyKey = `assistant-${assistantResult.value.trace_id}-${workOrderId}`
    const response = await triggerAutoDispatch(workOrderId, idempotencyKey)
    lookupThreadId.value = response.data?.data?.thread_id || ''
    ElMessage.success('Java 已受理请求并写入异步派单队列')
  } finally {
    assistantDispatchLoading.value = false
  }
}

const routeLabel = route => ({
  KNOWLEDGE_QA: '知识问答', DIRECT_DISPATCH: '直接派单',
  INCIDENT_INVESTIGATION: '故障调查', NEEDS_CLARIFICATION: '需要澄清'
}[route] || route)

const executionModeLabel = mode => ({
  qa: 'RAG QA', clarification: '澄清交互', single_agent: 'Single-Agent',
  multi_agent_planning: 'Multi-Agent Planning',
  java_dispatch_handoff: 'Java Outbox 安全交接'
}[mode] || mode)

const fillIds = () => {
  const suffix = Date.now().toString(36)
  dispatchForm.value.event_id ||= `ui-event-${suffix}`
  dispatchForm.value.dispatch_id ||= `ui-dispatch-${suffix}`
  dispatchForm.value.trace_id ||= `ui-trace-${suffix}`
}

const runDispatch = async () => {
  if (!dispatchForm.value.work_order_id) return ElMessage.warning('请输入工单 ID')
  fillIds()
  dispatchLoading.value = true
  try {
    const { tenant_id: tenantId, ...request } = dispatchForm.value
    dispatchResult.value = (await startDispatch({
      ...request,
      trigger: 'manual',
      deadline_seconds: 60
    }, tenantId)).data
    lookupThreadId.value = dispatchResult.value.thread_id
    if (needsApproval.value && candidates.value.length) {
      approval.value.worker_id = candidates.value[0].worker_id
    }
    ElMessage.success(needsApproval.value ? '决策已生成，等待人工审批' : '派单流程已完成')
  } finally {
    dispatchLoading.value = false
  }
}

const enqueueDispatch = async () => {
  if (!dispatchForm.value.work_order_id) return ElMessage.warning('请输入工单 ID')
  dispatchLoading.value = true
  try {
    if (manualIdempotencyOrder.value !== dispatchForm.value.work_order_id) {
      manualIdempotencyOrder.value = dispatchForm.value.work_order_id
      manualIdempotencyKey.value = `manual-ui-${dispatchForm.value.work_order_id}-${Date.now().toString(36)}`
    }
    const response = await triggerAutoDispatch(
      dispatchForm.value.work_order_id, manualIdempotencyKey.value
    )
    lookupThreadId.value = response.data?.data?.thread_id || ''
    ElMessage.success('自动派单事件已由 Java 受理，请稍后查询任务状态')
  } finally {
    dispatchLoading.value = false
  }
}

const submitApproval = async approved => {
  if (!approval.value.reviewer_id || !approval.value.reason) {
    return ElMessage.warning('请填写审核人和审批说明')
  }
  if (approved && !approval.value.worker_id) return ElMessage.warning('请选择维修员')
  dispatchLoading.value = true
  try {
    dispatchResult.value = (await resumeDispatch(dispatchResult.value.thread_id, {
      approved,
      worker_id: approved ? approval.value.worker_id : null,
      reason: approval.value.reason
    }, dispatchForm.value.tenant_id, approval.value.reviewer_id)).data
    ElMessage.success(approved ? '审批已提交' : '已拒绝本次派单')
  } finally {
    dispatchLoading.value = false
  }
}

const lookup = async () => {
  if (!lookupThreadId.value.trim()) return ElMessage.warning('请输入完整 thread_id')
  dispatchLoading.value = true
  try {
    dispatchResult.value = (await getDispatchStatus(
      lookupThreadId.value.trim(), dispatchForm.value.tenant_id
    )).data
    history.value = (await getDispatchHistory(
      lookupThreadId.value.trim(), dispatchForm.value.tenant_id
    )).data
  } finally {
    dispatchLoading.value = false
  }
}

const retry = async () => {
  dispatchLoading.value = true
  try {
    dispatchResult.value = (await retryDispatch(
      dispatchResult.value.thread_id, dispatchForm.value.tenant_id
    )).data
  } finally {
    dispatchLoading.value = false
  }
}

const statusLabel = status => ({
  awaiting_approval: '等待审批', audited: '已审计完成', failed: '执行失败',
  denied: '已拒绝', verified: '已核验', executing: '执行中'
}[status] || status || '尚未执行')
</script>

<template>
  <div class="agent-page">
    <section class="agent-intro">
      <div><span class="section-kicker">FLOWFIX AGENT</span><h2>智能运维协作中心</h2><p>答案附带知识证据，派单保留快照、决策、审批、写入和最终核验。</p></div>
      <button
        class="agent-badge"
        type="button"
        :title="'点击重新检查 Agent 就绪状态'"
        :disabled="readinessLoading"
        @click="checkReadiness({ notify: true })"
      ><i :class="{ degraded: !agentReady }"></i>{{ readinessLabel }}</button>
    </section>

    <el-tabs v-model="activeTab" class="agent-tabs">
      <el-tab-pane name="assistant">
        <template #label><span class="tab-label"><el-icon><MagicStick /></el-icon>运维智能助理</span></template>
        <div class="knowledge-layout">
          <section class="agent-card question-card">
            <span class="section-kicker">UNIFIED ASSISTANT</span><h3>用自然语言发起运维任务</h3>
            <p class="assistant-help">系统会自动路由到知识问答、低成本单 Agent 调查或多 Agent 规划；派单必须由管理员确认并交给 Java。</p>
            <el-input v-model="assistantMessage" type="textarea" :rows="6" maxlength="2000" show-word-limit placeholder="例如：调查设备 DEV-1003 的异常原因；把工单 1001 自动派单" @keyup.ctrl.enter="runAssistant" />
            <div class="assistant-options">
              <el-input v-model="assistantTenant" placeholder="租户 ID"><template #prepend>Tenant</template></el-input>
              <el-input v-model="assistantThreadId" placeholder="会话 ID"><template #prepend>Thread</template></el-input>
            </div>
            <div class="question-actions"><small>信息不全时在同一 Thread 中继续补充</small><el-button type="primary" :loading="assistantLoading" @click="runAssistant"><el-icon><Search /></el-icon>执行</el-button></div>
          </section>
          <section class="agent-card answer-card" v-loading="assistantLoading">
            <div v-if="assistantResult">
              <div class="assistant-route">
                <el-tag type="success">{{ routeLabel(assistantResult.route_type) }}</el-tag>
                <el-tag effect="plain">{{ executionModeLabel(assistantResult.execution_mode) }}</el-tag>
                <span>{{ assistantResult.outcome }}</span>
              </div>
              <div class="assistant-trace">Trace {{ assistantResult.trace_id }} · {{ assistantResult.route_reason_code }}</div>
              <div class="answer-content">{{ assistantResult.message }}</div>
              <el-alert v-if="assistantResult.missing_fields?.length" type="warning" :closable="false" :title="`请补充：${assistantResult.missing_fields.join('、')}`" />
              <div v-if="assistantResult.investigation" class="assistant-summary">
                <span>停止原因 <strong>{{ assistantResult.investigation.stop_reason }}</strong></span>
                <span>执行步数 <strong>{{ assistantResult.investigation.steps }}</strong></span>
                <span>证据数 <strong>{{ assistantEvidenceRefs.length }}</strong></span>
              </div>
              <div v-if="assistantResult.planning" class="assistant-summary">
                <span>计划状态 <strong>{{ assistantResult.planning.status }}</strong></span>
                <span>计划版本 <strong>v{{ assistantResult.planning.plan_version }}</strong></span>
                <span>制品数 <strong>{{ assistantResult.planning.artifacts?.length || 0 }}</strong></span>
              </div>
              <div v-if="assistantCitations.length" class="citation-list">
                <h4>引用依据</h4>
                <div v-for="item in assistantCitations" :key="item.citation_id"><span>[{{ item.citation_id }}]</span><p><strong>{{ item.title }}</strong><small>{{ item.section_path }}</small></p></div>
              </div>
              <div v-if="assistantEvidenceRefs.length" class="assistant-evidence"><strong>Evidence refs</strong><code v-for="refId in assistantEvidenceRefs" :key="refId">{{ refId }}</code></div>
              <div v-if="assistantResult.next_action?.type === 'trigger_java_dispatch'" class="approval-panel">
                <h4>管理员派单确认</h4>
                <p>工单 {{ assistantResult.next_action.continuation_id }} 将通过 Java 鉴权、Outbox 与 RabbitMQ 进入派单链路。</p>
                <el-button v-if="isAdmin" type="primary" :loading="assistantDispatchLoading" @click="confirmAssistantDispatch">确认进入异步派单队列</el-button>
                <el-alert v-else type="warning" :closable="false" title="当前账号不是管理员，不能触发派单" />
              </div>
            </div>
            <el-empty v-else description="路由决策、执行模式、答案和证据将在这里呈现" :image-size="88" />
          </section>
        </div>
      </el-tab-pane>

      <el-tab-pane name="knowledge">
        <template #label><span class="tab-label"><el-icon><MagicStick /></el-icon>知识助手</span></template>
        <div class="knowledge-layout">
          <section class="agent-card question-card">
            <span class="section-kicker">ASK WITH EVIDENCE</span><h3>询问平台与运维知识</h3>
            <el-input v-model="question" type="textarea" :rows="5" maxlength="2000" show-word-limit placeholder="输入设备、工单、派单或平台架构相关问题" @keyup.ctrl.enter="ask" />
            <el-input v-model="knowledgeTenant" placeholder="租户 ID，例如 default 或 public"><template #prepend>Tenant</template></el-input>
            <div class="question-actions"><small>Ctrl + Enter 快速发送</small><el-button type="primary" :loading="asking" @click="ask"><el-icon><Search /></el-icon>生成答案</el-button></div>
          </section>
          <section class="agent-card answer-card" v-loading="asking">
            <div v-if="answer">
              <div class="answer-meta"><span><CircleCheck />已完成引用校验</span><small>Trace {{ answer.trace_id }}</small></div>
              <div class="answer-content">{{ answer.answer }}</div>
              <div v-if="answer.citations?.length" class="citation-list">
                <h4>参考依据</h4>
                <div v-for="item in answer.citations" :key="item.citation_id"><span>[{{ item.citation_id }}]</span><p><strong>{{ item.title }}</strong><small>{{ item.section_path }}</small></p></div>
              </div>
            </div>
            <el-empty v-else description="答案和引用证据将在这里呈现" :image-size="88" />
          </section>
        </div>
      </el-tab-pane>

      <el-tab-pane v-if="isAdmin" name="dispatch">
        <template #label><span class="tab-label"><el-icon><Clock /></el-icon>智能派单</span></template>
        <div class="dispatch-layout" v-loading="dispatchLoading">
          <section class="agent-card dispatch-form-card">
            <div class="card-heading"><div><span class="section-kicker">NEW DISPATCH</span><h3>发起真实派单</h3><p>正式入口经 Java 鉴权并写入 Outbox；同步入口仅用于调试决策与 HITL。</p></div></div>
            <el-form :model="dispatchForm" label-position="top">
              <div class="form-grid">
                <el-form-item label="工单 ID" required><el-input v-model="dispatchForm.work_order_id" placeholder="请输入全新的专用测试工单 ID" /></el-form-item>
                <el-form-item label="租户"><el-input v-model="dispatchForm.tenant_id" /></el-form-item>
                <el-form-item label="Event ID"><el-input v-model="dispatchForm.event_id" placeholder="留空自动生成" /></el-form-item>
                <el-form-item label="Dispatch ID"><el-input v-model="dispatchForm.dispatch_id" placeholder="留空自动生成" /></el-form-item>
              </div>
              <el-button type="primary" @click="enqueueDispatch"><el-icon><MagicStick /></el-icon>进入异步派单队列</el-button>
              <el-button plain @click="runDispatch">同步调试 / HITL</el-button>
            </el-form>
            <el-divider>或查询既有任务</el-divider>
            <div class="lookup-row"><el-input v-model="lookupThreadId" placeholder="完整 thread_id，例如 dispatch:default:ui-dispatch-xxx" /><el-button :icon="Search" @click="lookup">查询</el-button></div>
          </section>

          <section class="agent-card dispatch-result-card">
            <template v-if="dispatchResult">
              <div class="result-status"><span :class="dispatchResult.status"></span><div><small>CURRENT STATUS</small><strong>{{ statusLabel(dispatchResult.status) }}</strong></div><code>{{ dispatchResult.thread_id }}</code></div>
              <div v-if="dispatchResult.assignment_outcome" class="outcome-grid">
                <div><small>工单</small><strong>{{ dispatchResult.assignment_outcome.work_order_id }}</strong></div>
                <div><small>维修员</small><strong>{{ dispatchResult.assignment_outcome.assigned_worker_id || '—' }}</strong></div>
                <div><small>版本</small><strong>{{ dispatchResult.assignment_outcome.work_order_version ?? '—' }}</strong></div>
                <div><small>结果</small><strong>{{ dispatchResult.assignment_outcome.status }}</strong></div>
              </div>
              <div v-if="needsApproval" class="approval-panel">
                <h4>人工审批</h4>
                <el-form label-position="top">
                  <el-form-item label="选择候选维修员"><el-select v-model="approval.worker_id" style="width: 100%"><el-option v-for="candidate in candidates" :key="candidate.worker_id" :label="`${candidate.worker_id} · score ${candidate.total_score}`" :value="candidate.worker_id" /></el-select></el-form-item>
                  <el-form-item label="审核人"><el-input v-model="approval.reviewer_id" placeholder="请输入审核人标识" /></el-form-item>
                  <el-form-item label="审批说明"><el-input v-model="approval.reason" type="textarea" :rows="2" /></el-form-item>
                  <div class="approval-actions"><el-button type="danger" plain @click="submitApproval(false)">拒绝</el-button><el-button type="primary" @click="submitApproval(true)">批准并执行</el-button></div>
                </el-form>
              </div>
              <div v-if="dispatchResult.errors?.length" class="error-list"><strong>异常信息</strong><span v-for="error in dispatchResult.errors" :key="error">{{ error }}</span></div>
              <div class="result-actions"><el-button v-if="dispatchResult.status === 'failed'" :icon="Refresh" @click="retry">从检查点重试</el-button><span v-if="history.length"><Document /> {{ history.length }} 个状态快照</span></div>
            </template>
            <el-empty v-else description="派单状态、候选排名与最终 outcome 将显示在这里" :image-size="88" />
          </section>
        </div>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>
