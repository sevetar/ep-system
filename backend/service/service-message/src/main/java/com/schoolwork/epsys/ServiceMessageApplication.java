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
@ServletComponentScan
@MapperScan("com.schoolwork.epsys.message.mapper")
@ComponentScan("com.schoolwork") // 添加对 model 包的扫描
@EnableDiscoveryClient
@EnableFeignClients(basePackages = {
        "com.schoolwork.epsys.acl.client"
})
public class ServiceMessageApplication {
    public static void main(String[] args) {
        SpringApplication.run(ServiceMessageApplication.class, args);
    }
}
