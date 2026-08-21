package com.schoolwork.epsys;

import org.mybatis.spring.annotation.MapperScan;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.web.servlet.ServletComponentScan;
import org.springframework.cache.annotation.EnableCaching;
import org.springframework.cloud.client.discovery.EnableDiscoveryClient;
import org.springframework.cloud.openfeign.EnableFeignClients;
import org.springframework.context.annotation.ComponentScan;
import org.springframework.scheduling.annotation.EnableScheduling;
//@ServletComponentScan
//@ComponentScan(basePackages = {"com.schoolwork.epsys.acl", "com.schoolwork.epsys.model"}) // 添加对 model 包的扫描
//@MapperScan("com.schoolwork.epsys.acl.mapper")
@SpringBootApplication
@EnableCaching
@MapperScan("com.schoolwork.epsys.acl.mapper")
@EnableDiscoveryClient
@EnableFeignClients(basePackages = {
        "com.schoolwork.epsys.device.client"
})
@EnableScheduling
public class ServiceAclApplication {

    public static void main(String[] args) {
        SpringApplication.run(ServiceAclApplication.class, args);
    }

}
