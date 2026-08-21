package com.schoolwork.epsys.model.message;

import com.baomidou.mybatisplus.annotation.TableName;
import java.io.Serializable;
import java.util.Date;
import lombok.Data;

/**
 * @TableName chat_massage
 */
@TableName(value ="chat_message")
@Data
public class ChatMessage implements Serializable {
    private Integer id;

    private Integer senderId;

    private Integer receiverId;

    private String content;

    private Integer isRead;

    private Date createTime;

    private static final long serialVersionUID = 1L;
}