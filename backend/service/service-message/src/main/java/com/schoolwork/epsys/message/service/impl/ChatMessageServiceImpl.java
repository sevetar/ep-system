package com.schoolwork.epsys.message.service.impl;


import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import com.schoolwork.epsys.message.mapper.ChatMessageMapper;
import com.schoolwork.epsys.message.service.ChatMessageService;
import com.schoolwork.epsys.model.message.ChatMessage;
import org.springframework.stereotype.Service;
import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;

import java.util.List;

/**
* @author 27959
* @description 针对表【chat_massage】的数据库操作Service实现
* @createDate 2025-04-15 16:29:44
*/
@Service
public class ChatMessageServiceImpl extends ServiceImpl<ChatMessageMapper, ChatMessage>
    implements ChatMessageService {

}
