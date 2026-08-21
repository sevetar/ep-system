package com.schoolwork.epsys.model.acl;

import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.io.Serializable;
import java.util.Date;

/**
 * @TableName user
 */
@TableName(value ="user")
@Data
public class User implements Serializable {
    private Integer id;

    private String username;

    private String password;

    private String phone;

    private Integer status;

    private String avatar;

    private Date lastTime;

    private Date createTime;

    private static final long serialVersionUID = 1L;
}