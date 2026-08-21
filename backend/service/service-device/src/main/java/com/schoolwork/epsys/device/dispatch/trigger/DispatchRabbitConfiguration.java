package com.schoolwork.epsys.device.dispatch.trigger;

import org.springframework.amqp.core.Binding;
import org.springframework.amqp.core.BindingBuilder;
import org.springframework.amqp.core.DirectExchange;
import org.springframework.amqp.core.Queue;
import com.schoolwork.epsys.device.knowledge.WorkOrderKnowledgeResultListener;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class DispatchRabbitConfiguration {

    @Bean
    DirectExchange flowfixAgentExchange() {
        return new DirectExchange(DispatchOutboxPublisher.EXCHANGE, true, false);
    }

    @Bean
    Queue workOrderKnowledgeResultQueue() {
        return new Queue(WorkOrderKnowledgeResultListener.RESULT_QUEUE, true);
    }

    @Bean
    Binding workOrderKnowledgeResultBinding(DirectExchange flowfixAgentExchange,
                                            Queue workOrderKnowledgeResultQueue) {
        return BindingBuilder.bind(workOrderKnowledgeResultQueue)
                .to(flowfixAgentExchange)
                .with(WorkOrderKnowledgeResultListener.RESULT_ROUTING_KEY);
    }
}
