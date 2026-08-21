<script setup>
import { ref, watch, nextTick, onMounted, onBeforeUnmount } from 'vue'
import { ElMessage } from 'element-plus'
import { sendMsg } from '@/utils/websocket.js'
import { subscribe, unsubscribe } from '@/utils/websocket.js'
import { getAllABMessage } from '@/api/chat.js'
import useUserInfoStore from '@/stores/userInfo.js'

const props = defineProps({
  chat: Object
})

const userInfoStore = useUserInfoStore()
const currentUserId = userInfoStore.info.id
const messages = ref([])
const input = ref('')
const chatBody = ref(null)

const scrollToBottom = () => {
  if (chatBody.value) {
    chatBody.value.scrollTop = chatBody.value.scrollHeight
  }
}

const handlePrivate = (msg) => {
  if (props.chat && msg.senderId === props.chat.id) {
    messages.value.push({
      id: Date.now(),
      from: 'other',
      content: msg.content
    })
    nextTick(scrollToBottom)
  }
}

const getABMessage = async () => {
  if (!props.chat || !currentUserId) return

  const params = {
    senderId: currentUserId,
    receiverId: props.chat.id
  }
  const result = await getAllABMessage(params)

  if (result.data.code === 200) {
    messages.value = result.data.data.chatMessages.map(msg => ({
      id: msg.id,
      from: msg.senderId === currentUserId ? 'me' : 'other',
      content: msg.content
    }))
    nextTick(scrollToBottom)
  }
}
watch(() => props.chat?.id, () => {
  if (props.chat) {
    getABMessage()
    nextTick(scrollToBottom)
  }
})


onMounted(() => {
  getABMessage()
  subscribe('/user/queue/messages', handlePrivate)
})

onBeforeUnmount(() => {
  // ✅ 页面卸载时取消订阅（必须使用同一个 callback）
  unsubscribe(handlePrivate)
})

const sendMessage = () => {
  if (!input.value.trim() || !props.chat) return

  const msg = {
    receiverId: props.chat.id,
    senderId: currentUserId,
    content: input.value,
    username: props.chat.username
  }

  messages.value.push({
    id: Date.now(),
    from: 'me',
    content: input.value
  })

  try {
    sendMsg('/app/chat/chatBackData', msg)
  } catch {
    messages.value.pop()
    ElMessage.warning('消息通道正在重连，请稍后再试')
    return
  }
  input.value = ''
  nextTick(scrollToBottom)
}
</script>


<template>
  <div class="chat-window-inner" v-if="chat">
    <div class="chat-header">
      <h3>{{ chat.username }}</h3>
    </div>
    
    <div class="chat-body" ref="chatBody">
      <div
        v-for="msg in messages"
        :key="msg.id"
        :class="['chat-msg', msg.from === 'me' ? 'me' : 'other']"
      >
        <div class="chat-content">{{ msg.content }}</div>
      </div>
    </div>

    <div class="chat-footer">
      <el-input
        v-model="input"
        type="textarea"
        :rows="2"
        placeholder="请输入消息"
      />
      <el-button type="primary" @click="sendMessage">发送</el-button>
    </div>

  </div>
  <div v-else class="no-chat">请选择聊天对象</div>
</template>

<style scoped>
.chat-window-inner {
  display: flex;
  flex-direction: column;
  height: 100%;
}
.chat-header {
  padding: 10px;
  background: #f2f2f2;
  border-bottom: 1px solid #ddd;
}
.chat-body {
  flex: 1;
  padding: 10px;
  overflow-y: auto;
  background-color: #fafafa;
}
.chat-footer {
  padding: 10px;
  display: flex;
  gap: 10px;
  align-items: flex-start;
  background: #f9f9f9;
  border-top: 1px solid #ddd;
}
.chat-msg {
  margin-bottom: 10px;
}
.chat-msg.me {
  text-align: right;
}
.chat-content {
  display: inline-block;
  padding: 6px 12px;
  border-radius: 10px;
  background-color: #e4f1ff;
}
.chat-msg.other .chat-content {
  background-color: #fff;
  border: 1px solid #ccc;
}
.no-chat {
  text-align: center;
  margin-top: 100px;
  font-size: 16px;
  color: #999;
}
</style>
