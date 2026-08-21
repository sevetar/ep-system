package com.schoolwork.epsys.mq.config;

import org.springframework.amqp.core.*;
import org.springframework.amqp.rabbit.connection.ConnectionFactory;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.amqp.support.converter.Jackson2JsonMessageConverter;
import org.springframework.amqp.support.converter.MessageConverter;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import static com.schoolwork.epsys.mq.constant.MqConst.*;

@Configuration
public class MQConfig {

    // 消息转换器
    @Bean
    public MessageConverter messageConverter() {
        return new Jackson2JsonMessageConverter();
    }

    // RabbitTemplate 设置消息转换器
    @Bean
    public RabbitTemplate rabbitTemplate(ConnectionFactory connectionFactory, MessageConverter messageConverter) {
        RabbitTemplate template = new RabbitTemplate(connectionFactory);
        template.setMessageConverter(messageConverter);
        template.setMandatory(true);
        return template;
    }

//    public static final String REPAIR_EXCHANGE = "repair_exchange";
//    public static final String REPAIR_APPLY_QUEUE = "repair_apply_queue"; // 申请成为维修人员


    //维修人员审批
    @Bean
    public Exchange repairExchange() {
        return ExchangeBuilder.directExchange(REPAIR_EXCHANGE).durable(true).build();
    }
    @Bean
    public Queue repairApplyQueue() {
        return QueueBuilder.durable(REPAIR_APPLY_QUEUE).build();
    }
    @Bean
    public Binding repairApplyBinding() {
        return BindingBuilder.bind(repairApplyQueue()).to(repairExchange()).with(REPAIR_APPLY_QUEUE).noargs();
    }



    //审批结果通知
    @Bean
    public DirectExchange approvalDirectExchange() {
        return ExchangeBuilder.directExchange(APPROVAL_DIRECT_EXCHANGE).durable(true).build();
    }
    @Bean
    public Queue userNotifyQueue() {
        return QueueBuilder.durable(USER_NOTIFY_QUEUE).build();
    }
    @Bean
    public Binding userNotifyBinding() {
        return BindingBuilder.bind(userNotifyQueue()).to(approvalDirectExchange()).with(USER_NOTIFY_ROUTING_KEY);
    }
    @Bean
    public Queue repairmanRefreshQueue() {
        return QueueBuilder.durable(REPAIR_MAN_REFRESH_QUEUE).build();
    }
    @Bean
    public Binding repairmanRefreshBinding() {
        return BindingBuilder.bind(repairmanRefreshQueue()).to(approvalDirectExchange()).with(REPAIRMAN_REFRESH_ROUTING_KEY);
    }




    //设备详情上下架
    @Bean
    public DirectExchange DeviceInstanceExchange() {
        return ExchangeBuilder.directExchange(DEVICE_INSTANCE_EXCHANGE).durable(true).build();
    }
    @Bean
    public Queue increaseDeviceInstanceQueue() {
        return QueueBuilder.durable(INCREASE_DEVICE_INSTANCE_QUEUE).build();
    }
    @Bean
    public Queue decreaseDeviceInstanceQueue() {
        return QueueBuilder.durable(DECREASE_DEVICE_INSTANCE_QUEUE).build();
    }
    @Bean
    public Binding increaseDeviceInstanceBinding() {
        return BindingBuilder.bind(increaseDeviceInstanceQueue()).to(DeviceInstanceExchange()).with(INCREASE_DEVICE_INSTANCE_ROUTING_KEY);
    }
    @Bean
    public Binding decreaseDeviceInstanceBinding() {
        return BindingBuilder.bind(decreaseDeviceInstanceQueue()).to(DeviceInstanceExchange()).with(DECREASE_DEVICE_INSTANCE_ROUTING_KEY);
    }

    @Bean
    public DirectExchange deviceBindingExchange() {
        return ExchangeBuilder.directExchange(DEVICE_BINDING_EXCHANGE).durable(true).build();
    }

    @Bean
    public Queue deviceBindingRequestQueue() {
        return QueueBuilder.durable(DEVICE_BINDING_REQUEST_QUEUE).build();
    }

    @Bean
    public Queue deviceBindingResultQueue() {
        return QueueBuilder.durable(DEVICE_BINDING_RESULT_QUEUE).build();
    }

    @Bean
    public Binding deviceBindingRequestBinding() {
        return BindingBuilder.bind(deviceBindingRequestQueue())
                .to(deviceBindingExchange()).with(DEVICE_BINDING_REQUEST_ROUTING_KEY);
    }

    @Bean
    public Binding deviceBindingResultBinding() {
        return BindingBuilder.bind(deviceBindingResultQueue())
                .to(deviceBindingExchange()).with(DEVICE_BINDING_RESULT_ROUTING_KEY);
    }




}
