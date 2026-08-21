package com.schoolwork.epsys.message.config;

import com.schoolwork.epsys.model.message.MyPrincipal;
import com.schoolwork.epsys.utils.JwtUtils;
import io.jsonwebtoken.Claims;
import org.springframework.messaging.Message;
import org.springframework.messaging.MessageChannel;
import org.springframework.messaging.simp.stomp.StompCommand;
import org.springframework.messaging.simp.stomp.StompHeaderAccessor;
import org.springframework.messaging.support.ChannelInterceptor;
import org.springframework.messaging.support.MessageHeaderAccessor;
import org.springframework.stereotype.Component;

@Component
public class WebSocketAuthChannelInterceptor implements ChannelInterceptor {

    @Override
    public Message<?> preSend(Message<?> message, MessageChannel channel) {
        // 获取 STOMP header
        StompHeaderAccessor accessor = MessageHeaderAccessor.getAccessor(message, StompHeaderAccessor.class);
        if (StompCommand.CONNECT.equals(accessor.getCommand())) {
            // 拿 token
            String token = accessor.getFirstNativeHeader("Authorization");
            if (token == null) {
                throw new IllegalArgumentException("未提供 token");
            }
            Claims claims = JwtUtils.parseJwt(token);
            // 校验 token（你可以用 JWT 工具类）
            String username = claims.get("username", String.class); // 假设你有 JwtUtils 工具类

            if (username == null) {
                throw new IllegalArgumentException("无效 token");
            }

            // 设置认证用户
            accessor.setUser(new MyPrincipal(username)); // 实现 java.security.Principal

        }
        return message;
    }
}
