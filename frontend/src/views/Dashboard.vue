<script setup>
import {
  ArrowRight,
  ChatDotRound,
  CircleCheck,
  Connection,
  Cpu,
  MagicStick,
  Tickets,
  Warning
} from '@element-plus/icons-vue'
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { getAgentReadiness } from '@/api/agent.js'
import useUserInfoStore from '@/stores/userInfo.js'

const router = useRouter()
const userStore = useUserInfoStore()
const loading = ref(true)
const readiness = ref(null)

const displayName = computed(() => userStore.info.nickname || userStore.info.username || '用户')
const healthyCount = computed(() => {
  const dependencies = readiness.value?.dependencies || {}
  return Object.values(dependencies).filter(value => value === 'ok').length
})

const loadReadiness = async () => {
  loading.value = true
  try {
    readiness.value = (await getAgentReadiness()).data
  } catch {
    readiness.value = { status: 'degraded', dependencies: {} }
  } finally {
    loading.value = false
  }
}

onMounted(loadReadiness)
</script>

<template>
  <div class="dashboard-page">
    <section class="dashboard-hero">
      <div class="hero-copy">
        <span class="hero-kicker">GOOD DAY, {{ displayName.toUpperCase() }}</span>
        <h2>让设备、工单与智能决策<br><em>在一个工作台协同。</em></h2>
        <p>从资产状态到维修闭环，再到可解释的 AI 派单，FlowFix 帮助团队聚焦真正需要处理的异常。</p>
        <div class="hero-actions">
          <el-button type="primary" size="large" @click="router.push('/agent/console')">
            打开 AI 智能中心<el-icon class="el-icon--right"><ArrowRight /></el-icon>
          </el-button>
          <el-button size="large" @click="router.push('/order/orderManage')">查看工单</el-button>
        </div>
      </div>
      <div class="hero-visual" aria-hidden="true">
        <div class="orbit orbit-one"></div><div class="orbit orbit-two"></div>
        <div class="core-node"><Connection /></div>
        <span class="satellite satellite-one"><Cpu /></span>
        <span class="satellite satellite-two"><MagicStick /></span>
        <span class="satellite satellite-three"><Tickets /></span>
      </div>
    </section>

    <section class="dashboard-grid">
      <div class="overview-card service-health" v-loading="loading">
        <div class="card-heading">
          <div><span class="section-kicker">SYSTEM STATUS</span><h3>联调服务状态</h3></div>
          <button type="button" class="text-button" @click="loadReadiness">刷新</button>
        </div>
        <div class="health-summary">
          <span class="health-icon" :class="readiness?.status">
            <CircleCheck v-if="readiness?.status === 'ok'" /><Warning v-else />
          </span>
          <div><strong>{{ readiness?.status === 'ok' ? '核心链路运行正常' : '部分依赖暂不可用' }}</strong><small>{{ healthyCount }} 个 Agent 依赖已就绪</small></div>
        </div>
        <div class="dependency-list">
          <div v-for="(status, name) in readiness?.dependencies" :key="name">
            <span>{{ name === 'java_dispatch' ? 'Java Dispatch' : 'Elasticsearch' }}</span>
            <em :class="status">{{ status === 'ok' ? '在线' : '不可用' }}</em>
          </div>
          <el-empty v-if="!loading && !Object.keys(readiness?.dependencies || {}).length" description="暂未获取到服务状态" :image-size="52" />
        </div>
      </div>

      <div class="overview-card workflow-card">
        <div class="card-heading"><div><span class="section-kicker">WORKFLOW</span><h3>智能派单链路</h3></div></div>
        <div class="workflow-list">
          <div><span>01</span><p><strong>冻结真实快照</strong><small>读取 Java 工单与候选维修员</small></p></div>
          <div><span>02</span><p><strong>确定性决策</strong><small>资格门禁、评分与风险分流</small></p></div>
          <div><span>03</span><p><strong>人工安全兜底</strong><small>高风险或同分场景等待审批</small></p></div>
          <div><span>04</span><p><strong>核验最终结果</strong><small>以 Java outcome 为业务真相</small></p></div>
        </div>
      </div>
    </section>

    <section class="quick-section">
      <div class="section-title"><span class="section-kicker">QUICK ACCESS</span><h3>常用工作入口</h3></div>
      <div class="quick-grid">
        <button type="button" @click="router.push('/device/manage')"><span><Cpu /></span><div><strong>设备资产</strong><small>查看模型与实例状态</small></div><ArrowRight /></button>
        <button type="button" @click="router.push('/order/orderManage')"><span><Tickets /></span><div><strong>工单中心</strong><small>处理审批与维修任务</small></div><ArrowRight /></button>
        <button type="button" @click="router.push('/agent/console')"><span><MagicStick /></span><div><strong>AI 智能中心</strong><small>知识问答与智能派单</small></div><ArrowRight /></button>
        <button type="button" @click="router.push('/message/manage')"><span><ChatDotRound /></span><div><strong>消息协作</strong><small>联系在线运维人员</small></div><ArrowRight /></button>
      </div>
    </section>
  </div>
</template>
