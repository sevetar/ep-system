package com.schoolwork.epsys.model.shared;

import lombok.Data;

import java.io.Serializable;
import java.util.Date;

@Data
public class UserNotification implements Serializable {
    private String username;

    private String Notification;

    private Integer senderId=10086;

    private Integer receiverId;

    private Integer isRead;

    private Date createTime;

    private static final long serialVersionUID = 1L;


}