package com.schoolwork.epsys.message.client;

import com.schoolwork.epsys.model.device.MaintainRecord;
import com.schoolwork.epsys.model.message.ChatMessage;
import org.springframework.cloud.openfeign.FeignClient;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestParam;

@FeignClient(name = "service-message", contextId = "messageFeign", path = "/msg")
public interface MessageFeignClient {

    // 给所有订阅了 /topic/maintain 的管理员发送维护广播
    @PostMapping("/sendToTopic4Maintain")
    void sendToTopic4Maintain();

    // 给指定用户推送私信（可选）
    @PostMapping("/sendToUser")
    String sendToUser(@RequestParam("toUsername") String toUsername, @RequestBody ChatMessage message);
}
