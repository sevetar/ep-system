package com.schoolwork.epsys.message.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.schoolwork.epsys.model.message.ChatMessage;
import org.apache.ibatis.annotations.Param;
import java.util.List;

/**
* @author 27959
* @description 针对表【chat_massage】的数据库操作Mapper
* @createDate 2025-04-15 16:29:44
* @Entity generator.message.ChatMessage
*/
public interface ChatMessageMapper extends BaseMapper<ChatMessage> {
    List<ChatMessage> getChatMessageFromAToB(@Param("userAId") Integer userAId, @Param("userBId") Integer userBId);
}
