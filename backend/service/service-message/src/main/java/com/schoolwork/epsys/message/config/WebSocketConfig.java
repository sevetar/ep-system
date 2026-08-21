package com.schoolwork.epsys.message.config;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.messaging.simp.config.ChannelRegistration;
import org.springframework.messaging.simp.config.MessageBrokerRegistry;
import org.springframework.web.socket.config.annotation.EnableWebSocketMessageBroker;
import org.springframework.web.socket.config.annotation.StompEndpointRegistry;
import org.springframework.web.socket.config.annotation.WebSocketMessageBrokerConfigurer;

@Configuration
@EnableWebSocketMessageBroker
public class WebSocketConfig implements WebSocketMessageBrokerConfigurer {

    // 注入自定义的 WebSocketAuthChannelInterceptor
    @Autowired
    private WebSocketAuthChannelInterceptor webSocketAuthChannelInterceptor;

    @Override
    public void configureClientInboundChannel(ChannelRegistration registration) {
        registration.interceptors(webSocketAuthChannelInterceptor);
    }

    @Override
    public void configureMessageBroker(MessageBrokerRegistry registry) {
        // 前缀 topic 表示广播（订阅通道）
        registry.enableSimpleBroker("/topic", "/queue"); // 点对点用 /queue
        // 客户端发送消息时的前缀（发消息用/app/xxx）
        registry.setApplicationDestinationPrefixes("/app");
        // 点对点通信设置
        registry.setUserDestinationPrefix("/user");
    }

    @Override
    public void registerStompEndpoints(StompEndpointRegistry registry) {
        // 原生 WebSocket，不使用 SockJS
        registry.addEndpoint("/ws")
                .setAllowedOriginPatterns("*"); // CORS 放开（开发环境）
    }

}
