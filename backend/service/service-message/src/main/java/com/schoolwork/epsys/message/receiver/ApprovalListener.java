package com.schoolwork.epsys.message.receiver;


import com.schoolwork.epsys.message.service.sendToTopic4MaintainRecordService;
import com.schoolwork.epsys.model.device.MaintainRecord;
import com.schoolwork.epsys.model.message.ChatMessage;
import com.schoolwork.epsys.model.shared.UserNotification;
import org.springframework.amqp.rabbit.annotation.RabbitListener;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.messaging.simp.SimpMessagingTemplate;
import org.springframework.stereotype.Component;

import java.io.Serializable;
import java.util.Date;
import java.util.UUID;

@Component
public class ApprovalListener {

    @Autowired
    private sendToTopic4MaintainRecordService sendToTopic4MaintainRecordServiceImpl;

    @Autowired
    SimpMessagingTemplate messagingTemplate;
    /**
     * 监听用户通知队列，推送审批通知
     */

    @RabbitListener(queues = "user_notify_queue")
    public void listenUserNotify(UserNotification userNotification) {
        System.out.println("收到用户通知消息：" + userNotification);
        // 这里可以进行推送，比如调用 WebSocket 给前端发消息
        // 或者存数据库，供前端轮询拉取
        ChatMessage chatMessage = new ChatMessage();
        UUID uuid = UUID.randomUUID();
        int id = uuid.toString().hashCode();
        chatMessage.setId(id);
        chatMessage.setSenderId(userNotification.getSenderId());
        chatMessage.setContent(userNotification.getNotification());
        chatMessage.setReceiverId(userNotification.getReceiverId());
        chatMessage.setIsRead(0);
        chatMessage.setCreateTime(new Date());
        messagingTemplate.convertAndSendToUser(userNotification.getUsername(), "/queue/messages", chatMessage);
    }

    @RabbitListener(queues = "repairman_refresh_queue")
    public void listenRepairmanRefresh(MaintainRecord maintainRecord) {
        System.out.println("收到维修人员刷新消息：" + maintainRecord);
        if(maintainRecord!=null){sendToTopic4MaintainRecordServiceImpl.sendToTopic4Maintain();}


    }
}
