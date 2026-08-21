<script setup>
import { ref } from 'vue'
import ChatList from './ChatList.vue'
import ChatWindow from './ChatWindow.vue'

const selectedChat = ref(null)

const handleChatSelect = (chat) => {
  selectedChat.value = chat
}
</script>

<!-- views/message/Manage.vue -->
<template>
  <div class="message-manage">
    <div class="chat-sidebar">
      <ChatList @selectChat="handleChatSelect" />
    </div>
    <div class="chat-window">
      <ChatWindow :chat="selectedChat" />
    </div>
  </div>
</template>


<style scoped>
.message-manage {
  display: flex;
  height: 100%;
  border: 1px solid #ddd;
}
.chat-sidebar {
  width: 300px;
  border-right: 1px solid #ccc;
  background-color: #f8f8f8;
}
.chat-window {
  flex: 1;
  background-color: #fff;
  display: flex;
  flex-direction: column;
}
</style>
