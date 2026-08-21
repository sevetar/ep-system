package com.schoolwork.epsys.message.service.impl;

import com.schoolwork.epsys.message.service.sendToTopic4MaintainRecordService;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.messaging.simp.SimpMessagingTemplate;
import org.springframework.stereotype.Service;

import java.util.HashMap;
import java.util.Map;


@Service
public class sendToTopic4MaintainRecordImpl implements sendToTopic4MaintainRecordService {

    @Autowired
    private SimpMessagingTemplate messagingTemplate;
    @Override
    public void sendToTopic4Maintain() {
        // 发送 JSON 格式的消息
        Map<String, Object> msg = new HashMap<>();
        msg.put("type", "refresh");
        msg.put("message", "需要刷新");
        messagingTemplate.convertAndSend("/topic/repairMan", msg);
    }
}
