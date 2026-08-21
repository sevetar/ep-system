<!-- views/message/ChatList.vue -->
<script setup>
import { onMounted, ref } from 'vue'
import {getOnlineUser} from "@/api/chat"
const chats = ref([
  { id: 1, username: '系统通知', avatar: 'https://via.placeholder.com/40', type: 'system' },
])

const emit = defineEmits(['selectChat'])
const activeId = ref(null)

//获取在线用户
const getAliveUsers = async () => {
  const res = await getOnlineUser()
  chats.value = res.data.data
}
onMounted(() => {
  getAliveUsers();
})

const onSelect = (id) => {
  const selected = chats.value.find(chat => chat.id.toString() === id)
  emit('selectChat', selected)
  activeId.value = id
}
</script>
<template>
    <el-scrollbar class="chat-list">
      <el-menu :default-active="activeId" class="el-menu-vertical-demo" @select="onSelect">
        <el-menu-item
          v-for="chat in chats"
          :key="chat.id"
          :index="chat.id.toString()"
        >
          <el-avatar :src="chat.avatar" size="small" />
          <span style="margin-left: 10px;">{{ chat.username }}</span>
        </el-menu-item>
      </el-menu>
    </el-scrollbar>
  </template>
  

  
  <style scoped>
  .chat-list {
    height: 100%;
    overflow: auto;
    padding-top: 10px;
  }
  </style>
  
