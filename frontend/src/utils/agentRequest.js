import axios from 'axios'
import { ElMessage } from 'element-plus'

const agentRequest = axios.create({
  baseURL: import.meta.env.VITE_AGENT_API_BASE || '/agent-api',
  timeout: 45000
})

agentRequest.interceptors.response.use(
  response => response,
  error => {
    const message = error.response?.data?.message
      || error.response?.data?.detail
      || (error.code === 'ECONNABORTED' ? 'Agent 请求超时' : 'Agent 服务暂时不可用')
    ElMessage.error(typeof message === 'string' ? message : 'Agent 请求失败')
    return Promise.reject(error)
  }
)

export default agentRequest
