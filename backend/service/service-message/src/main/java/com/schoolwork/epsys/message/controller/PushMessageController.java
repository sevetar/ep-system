package com.schoolwork.epsys.message.controller;

import com.schoolwork.epsys.message.service.sendToTopic4MaintainRecordService;
import com.schoolwork.epsys.model.acl.User;
import com.schoolwork.epsys.model.device.MaintainRecord;
import com.schoolwork.epsys.model.message.ChatMessage;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.messaging.simp.SimpMessagingTemplate;
import org.springframework.web.bind.annotation.*;

import java.util.HashMap;
import java.util.Map;

/**
 * WebSocket 消息推送接口，负责向指定用户或指定业务主题发送实时通知。
 */
@RestController
@RequestMapping("/msg")
public class PushMessageController {

    @Autowired
    private SimpMessagingTemplate messagingTemplate;

    @Autowired
    sendToTopic4MaintainRecordService sendToTopic4MaintainRecordServiceImpl;

    /**
     * 向指定用户名对应的用户队列定向推送聊天消息。
     */
    @PostMapping("/sendToUser")
    public String sendToUser(@RequestParam String toUsername, @RequestBody ChatMessage message) {
        // 发送到目标用户的队列（前端必须订阅 /user/queue/messages）
        messagingTemplate.convertAndSendToUser(toUsername, "/queue/messages", message);
        return "OK";
    }

    /**
     * 向审批主题广播刷新通知，提醒在线审批人员获取最新维护工单。
     */
    @RequestMapping("/sendToTopic4Maintain")
    public void sendToTopic4Maintain() {
        System.out.println("发送给在线的审批人员");
        // 发送 JSON 格式的消息
        Map<String, Object> msg = new HashMap<>();
        msg.put("type", "refresh");
        msg.put("message", "需要刷新");
        messagingTemplate.convertAndSend("/topic/approval", msg);
    }

    /**
     * 调用消息服务向在线维修人员广播维护工单刷新通知。
     */
    @RequestMapping("/sendToTopic4MaintainRecord")
    public void sendToTopic4MaintainRecord() {
        sendToTopic4MaintainRecordServiceImpl.sendToTopic4Maintain();
    }

//    @PostMapping("/sendToUserApprovaltaken")
//    public void sendToUserApprovaltaken() {
//        Integer userId= maintainRecord.getOperatorId();
//        //使用openfeign获取用户名称
//
//        // 发送到目标用户的队列（前端必须订阅 /user/queue/messages）
//        messagingTemplate.convertAndSendToUser(toUsername, "/queue/messages", maintainRecord);
//    }





}
