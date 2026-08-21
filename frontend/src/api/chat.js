import request from '@/utils/request.js'

//从redis中获取在线的用户
export const getOnlineUser = () => {
  return request.get('/chat/getOnlineUser')
}

//获取用户A和用户B的聊天记录
export const getAllABMessage = (params) => {
  return request.get('/chat/getAllABMessage',{params:params})
}
