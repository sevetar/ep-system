package com.schoolwork.epsys;

import org.mybatis.spring.annotation.MapperScan;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.web.servlet.ServletComponentScan;
import org.springframework.cache.annotation.EnableCaching;
import org.springframework.cloud.client.discovery.EnableDiscoveryClient;
import org.springframework.cloud.openfeign.EnableFeignClients;
import org.springframework.context.annotation.ComponentScan;

@SpringBootApplication
@EnableCaching
@EnableDiscoveryClient
@MapperScan("com.schoolwork.epsys.approval.mapper")
@EnableFeignClients(basePackages = {
        "com.schoolwork.epsys.acl.client",
        "com.schoolwork.epsys.message.client"
})
public class ServiceApprovalApplication {
    public static void main(String[] args) {
        SpringApplication.run(ServiceApprovalApplication.class, args);
    }
}
