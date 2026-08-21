package com.schoolwork.epsys.acl.saga;

import com.schoolwork.epsys.model.shared.DeviceBindingResultEventV1;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.ActiveProfiles;

import java.time.Instant;

import static com.schoolwork.epsys.model.shared.DeviceBindingContracts.*;
import static org.junit.jupiter.api.Assertions.*;

@SpringBootTest(properties = {
        "spring.cloud.nacos.discovery.enabled=false",
        "spring.cloud.discovery.enabled=false"
})
@ActiveProfiles("test")
class DeviceBindingSagaServiceIntegrationTest {

    private static final int DEVICE_ID = 99891;
    private static final int USER_ID = 99892;

    @Autowired
    private DeviceBindingSagaService sagaService;

    @Autowired
    private JdbcTemplate jdbcTemplate;

    @BeforeEach
    @AfterEach
    void cleanRows() {
        jdbcTemplate.update("DELETE FROM device_binding_outbox WHERE device_id = ?", DEVICE_ID);
        jdbcTemplate.update("DELETE FROM devicetousers WHERE device_id = ?", DEVICE_ID);
    }

    @Test
    void bindSuccessActivatesOwnershipAndDuplicateRequestIsIdempotent() {
        DeviceBindingSagaService.SagaRequestResult requested =
                sagaService.requestBind(USER_ID, DEVICE_ID, "bind-1");
        DeviceBindingSagaService.SagaRequestResult replay =
                sagaService.requestBind(USER_ID, DEVICE_ID, "ignored-replay-id");

        assertTrue(requested.accepted());
        assertEquals("PENDING", requested.status());
        assertEquals("bind-1", replay.requestId());
        assertEquals(1, outboxCount("bind-1"));
        assertFalse(sagaService.isActiveOwner(USER_ID, DEVICE_ID));

        sagaService.applyResult(result("bind-1", BIND_REQUESTED, "SUCCEEDED", null));

        assertEquals("ACTIVE", bindingStatus());
        assertTrue(sagaService.isActiveOwner(USER_ID, DEVICE_ID));
    }

    @Test
    void failedBindCompensatesRelationAndCanBeRetried() {
        sagaService.requestBind(USER_ID, DEVICE_ID, "bind-failed");
        sagaService.applyResult(result("bind-failed", BIND_REQUESTED, "FAILED", "DEVICE_STATUS_CONFLICT"));

        assertEquals("FAILED", bindingStatus());
        assertFalse(sagaService.isActiveOwner(USER_ID, DEVICE_ID));

        DeviceBindingSagaService.SagaRequestResult retry =
                sagaService.requestBind(USER_ID, DEVICE_ID, "bind-retry");
        assertEquals("PENDING", retry.status());
        assertEquals("PENDING_BIND", bindingStatus());
        assertEquals(1, outboxCount("bind-retry"));
    }

    @Test
    void failedUnbindRestoresActiveRelationAndSuccessRemovesIt() {
        sagaService.requestBind(USER_ID, DEVICE_ID, "bind-before-unbind");
        sagaService.applyResult(result("bind-before-unbind", BIND_REQUESTED, "SUCCEEDED", null));

        sagaService.requestUnbind(USER_ID, DEVICE_ID, "unbind-failed");
        sagaService.applyResult(result("unbind-failed", UNBIND_REQUESTED, "FAILED", "DEVICE_STATUS_CONFLICT"));
        assertEquals("ACTIVE", bindingStatus());

        sagaService.requestUnbind(USER_ID, DEVICE_ID, "unbind-success");
        sagaService.applyResult(result("unbind-success", UNBIND_REQUESTED, "SUCCEEDED", null));
        assertNull(jdbcTemplate.queryForObject(
                "SELECT MAX(binding_status) FROM devicetousers WHERE device_id = ?",
                String.class, DEVICE_ID));
    }

    private DeviceBindingResultEventV1 result(String requestId, String eventType,
                                               String status, String reasonCode) {
        return new DeviceBindingResultEventV1(SCHEMA_VERSION, "result-" + requestId,
                requestId, eventType, USER_ID, DEVICE_ID, status, reasonCode, Instant.now());
    }

    private String bindingStatus() {
        return jdbcTemplate.queryForObject(
                "SELECT binding_status FROM devicetousers WHERE device_id = ?",
                String.class, DEVICE_ID);
    }

    private int outboxCount(String requestId) {
        return jdbcTemplate.queryForObject(
                "SELECT COUNT(*) FROM device_binding_outbox WHERE request_id = ?",
                Integer.class, requestId);
    }
}
