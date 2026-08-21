package com.schoolwork.epsys.mq.config;

import jakarta.annotation.PostConstruct;
import org.springframework.amqp.core.ReturnedMessage;
import org.springframework.amqp.rabbit.connection.CorrelationData;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.stereotype.Component;

@Component
public class MQProducerAckConfig {

    private final RabbitTemplate rabbitTemplate;

    public MQProducerAckConfig(RabbitTemplate rabbitTemplate) {
        this.rabbitTemplate = rabbitTemplate;
    }

    @PostConstruct
    public void init() {
        // 确认消息是否发送到交换机
        rabbitTemplate.setConfirmCallback(new RabbitTemplate.ConfirmCallback() {
            @Override
            public void confirm(CorrelationData correlationData, boolean ack, String cause) {
                if (ack) {
                    System.out.println("消息成功发送到交换机！");
                } else {
                    System.out.println("消息发送到交换机失败，原因：" + cause);
                }
            }
        });

        // 确认消息是否从交换机路由到了队列
        rabbitTemplate.setReturnsCallback(returnedMessage -> {
            System.out.println("消息未能路由到队列：");
            System.out.println("消息内容：" + new String(returnedMessage.getMessage().getBody()));
            System.out.println("响应码：" + returnedMessage.getReplyCode());
            System.out.println("原因：" + returnedMessage.getReplyText());
            System.out.println("交换机：" + returnedMessage.getExchange());
            System.out.println("路由键：" + returnedMessage.getRoutingKey());
        });
    }
}
