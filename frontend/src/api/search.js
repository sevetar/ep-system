// src/api/search.js
import request from '@/utils/request'

export const searchDevice = (keyword) => {
  return request.get('/search', {
    params: { keyword }
  })
}



