package com.schoolwork.epsys.message.controller;


import com.schoolwork.epsys.common.Result;
import com.schoolwork.epsys.message.mapper.ChatMessageMapper;
import com.schoolwork.epsys.message.service.ChatMessageService;
import com.schoolwork.epsys.model.message.ChatMessage;
import com.schoolwork.epsys.utils.WebUtil;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.data.redis.core.RedisTemplate;
import org.springframework.messaging.handler.annotation.MessageMapping;
import org.springframework.messaging.handler.annotation.Payload;
import org.springframework.messaging.simp.SimpMessagingTemplate;
import org.springframework.messaging.simp.annotation.SendToUser;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.io.IOException;
import java.security.Principal;
import java.util.Date;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * 即时聊天接口，负责在线用户查询、历史消息查询以及 WebSocket 消息收发与落库。
 */
@RestController
@MessageMapping("/chat")
public class ChatMessageController {
    @Autowired
    private RedisTemplate redisTemplate;

    @Autowired
    ChatMessageMapper chatMessageMapper;



    private final SimpMessagingTemplate messagingTemplate;

    // 构造器注入，推荐方式
    public ChatMessageController(SimpMessagingTemplate messagingTemplate) {
        this.messagingTemplate = messagingTemplate;
    }

    /**
     * 补全消息的发送者和时间等信息，并将消息定向推送给接收用户。
     */
    @SendToUser("/queue/messages") // 仅推送给当前用户（可选）
    public void sendToUser(ChatMessage message, Principal principal) {
        // 获取发送者 ID（假设 token 或连接时设置了 principal）
        message.setSenderId(Integer.parseInt(principal.getName()));
        message.setCreateTime(new Date());
        message.setIsRead(0);

        // 保存消息到数据库（可选）
        // chatMessageService.save(message);

        // 使用 messagingTemplate 推送给用户2（接收者）
        messagingTemplate.convertAndSendToUser(
                message.getReceiverId().toString(), // 用户2的ID
                "/queue/messages",
                message
        );
    }

    /**
     * 从 Redis 查询当前处于在线状态的用户列表。
     */
    @RequestMapping("/getOnlineUser")
    public void getOnlineUser(HttpServletRequest req, HttpServletResponse resp) throws ServletException, IOException {
        String onlineUsersKey = "online:users";  // Hash的key名称
        List<Object> onlineUsers = redisTemplate.opsForHash().values(onlineUsersKey);
        Result result = Result.ok(onlineUsers);
        WebUtil.writeJson(resp, result);

    }

    /**
     * 查询发送方与接收方之间的全部历史聊天消息。
     */
    @RequestMapping("/getAllABMessage")
    public void getAllABMessage(HttpServletRequest req, HttpServletResponse resp,
                                @RequestParam("senderId") int senderId, @RequestParam("receiverId") int receiverId) throws ServletException, IOException {

        List<ChatMessage> chatMessages = chatMessageMapper.getChatMessageFromAToB(senderId, receiverId);
        Map data = new HashMap();
        data.put("chatMessages", chatMessages);
        Result result = Result.ok(data);
        WebUtil.writeJson(resp, result);

    }

    /**
     * 接收 WebSocket 聊天数据，将消息保存到数据库并推送给目标用户。
     */
    @MessageMapping("/chatBackData")
    public void chatBackData(@Payload Map<String, Object> data, Principal principal) {
        System.out.println("收到的数据 = " + data);

        // 构建 ChatMessage 对象
        ChatMessage message = new ChatMessage();
        message.setReceiverId(Integer.valueOf(data.get("receiverId").toString()));
        message.setSenderId(Integer.valueOf(data.get("senderId").toString()));
        message.setContent(data.get("content").toString());
        message.setCreateTime(new Date());
        message.setIsRead(1);

        // 你现在可以使用 username（如果你需要）
        String username = data.get("username").toString();
        System.out.println("对方用户名：" + username);

        chatMessageMapper.insert(message);

        messagingTemplate.convertAndSendToUser(
                username,
                "/queue/messages",
                message
        );
    }



}


