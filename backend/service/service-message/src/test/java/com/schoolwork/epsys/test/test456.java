package com.schoolwork.epsys.test;


import com.schoolwork.epsys.message.mapper.ChatMessageMapper;
import com.schoolwork.epsys.model.message.ChatMessage;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;

import java.util.List;

@SpringBootTest
public class test456 {

    @Autowired
    private ChatMessageMapper chatMessageMapper;
    Integer senderId = 2;
    Integer receiverId = 3;

   @Test
    void testSelect() {
       List<ChatMessage> chatMessages = chatMessageMapper.getChatMessageFromAToB(senderId, receiverId);
       for(ChatMessage chatMessage : chatMessages) {
           System.out.println(chatMessage.getContent());
       }
    }
}
