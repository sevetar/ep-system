package com.schoolwork.epsys.model.message;

import java.security.Principal;

/**
 * 功能描述：
 * websocket-自定义用户
 * @Author: nickel
 * @Date: 2021/4/2 14:37
 */
public class MyPrincipal implements Principal {
    private String name;
    public MyPrincipal(String name){
        this.name=name;
    }

    @Override
    public String getName() {
        return name;
    }
}
