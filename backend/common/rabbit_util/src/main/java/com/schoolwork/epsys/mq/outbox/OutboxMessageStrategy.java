package com.schoolwork.epsys.mq.outbox;

import org.springframework.amqp.rabbit.connection.CorrelationData;
import org.springframework.amqp.rabbit.core.RabbitTemplate;

/** 不同业务事件只负责消息构造与路由，不能改变可靠发布主流程。 */
public interface OutboxMessageStrategy<T> {

    String eventId(T event);

    void send(RabbitTemplate rabbitTemplate, T event, CorrelationData correlationData);
}
