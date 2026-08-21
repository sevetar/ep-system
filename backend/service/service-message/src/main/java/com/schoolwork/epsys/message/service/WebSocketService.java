//package com.schoolwork.epsys.message.service;
//
//import com.alibaba.fastjson2.JSON;
//import jakarta.annotation.Resource;
//import org.springframework.beans.factory.annotation.Autowired;
//import org.springframework.messaging.simp.SimpMessageSendingOperations;
//import org.springframework.messaging.simp.user.SimpUser;
//import org.springframework.messaging.simp.user.SimpUserRegistry;
//import org.springframework.stereotype.Service;
//
//import java.util.HashMap;
//import java.util.Map;
//
///**
// * 功能描述：
// * websocket发送信息入口
// * @Author: nickel
// * @Date: 2021/4/2 14:37
// */
//@Service
//@Slf4j
//public class WebSocketService {
//
//    private static final String HANDLER_NAME = "socketHandler";
//
//    @Resource
//    private MyRedisClient myRedisClient;
//    @Autowired
//    private SimpMessageSendingOperations simpMessageSendingOperations;
//
//    @Autowired
//    private SimpUserRegistry simpUserRegistry;
//
//    /**
//     * 服务端推送消息--一对一
//     * 单体服务
//     * 客服端 订阅地址为/users/{username}/message
//     *
//     * @param username
//     * @param message
//     */
//    public void pushMessage(String username, String message,String id) {
//        try {
//            //根据用户名查询当前节点在线用户
//            SimpUser simpUser = simpUserRegistry.getUser(username);
//            if (null == simpUser) {
//                return;
//            }
//            log.info("--服务端指定用户发送消息，to【{}】", simpUser.getName());
//            String nowTime = GaeaUtils.formatDate(new Date(), GaeaConstant.TIME_PATTERN);
//            GaeaWsMessage gaeaWsMessage = new GaeaWsMessage(id,message, nowTime);
//            simpMessageSendingOperations.convertAndSendToUser(username, "/message", JSON.toJSONString(gaeaWsMessage));
//        } catch (Exception e) {
//            e.printStackTrace();
//        }
//    }
//
//    /**
//     * 服务器端推送消息--广播//     * 客服端 订阅地址为/topic/message
//     * 单体服务
//     */
//    public void pushMessage(String message,String id) {
//        try {
//            String nowTime = GaeaUtils.formatDate(new Date(), GaeaConstant.TIME_PATTERN);
//            GaeaWsMessage gaeaWsMessage = new GaeaWsMessage(id,message, nowTime);
//            simpMessageSendingOperations.convertAndSend("/topic/message", JSON.toJSONString(gaeaWsMessage));
//        } catch (Exception e) {
//            e.printStackTrace();
//        }
//    }
//
//    /**
//     * 后台发送消息到redis
//     * 支持微服务
//     * @param commonMsgDto
//     */
//    public void sendMessage(CommonMsgDto commonMsgDto) {
//        log.info("【websocket消息】广播消息:" + JSON.toJSONString(commonMsgDto));
//        Map<String, String> msgMap = new HashMap<>();
//        msgMap.put("message", commonMsgDto.getMessage());
//        msgMap.put("id", commonMsgDto.getId());
//        myRedisClient.sendMessage(HANDLER_NAME, msgMap);
//    }
//
//    /**
//     * 此为单点消息--发送到redis
//     *
//     * @param userMsgDto
//     */
//    public void sendMessage(UserMsgDto userMsgDto) {
//        Map<String, String> msgMap = new HashMap<>();
//        msgMap.put("username", userMsgDto.getUsername());
//        msgMap.put("message", userMsgDto.getMessage());
//        msgMap.put("id", userMsgDto.getId());
//        myRedisClient.sendMessage(HANDLER_NAME, msgMap);
//    }
//
//    /**
//     * 此为单点消息(多人)
//     * 支持微服务
//     * @param userMsgDtos
//     */
//    public void sendMessage(List<UserMsgDto> userMsgDtos) {
//        if(CollectionUtils.isEmpty(userMsgDtos)){
//            return;
//        }
//        for (UserMsgDto userMsgDto : userMsgDtos) {
//            sendMessage(userMsgDto);
//        }
//    }
//
//}