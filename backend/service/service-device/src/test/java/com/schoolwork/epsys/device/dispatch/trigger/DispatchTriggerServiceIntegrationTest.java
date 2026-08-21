package com.schoolwork.epsys.device.dispatch.trigger;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.schoolwork.epsys.model.device.MaintainRecord;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.ActiveProfiles;

import java.util.Date;

import static org.junit.jupiter.api.Assertions.*;

@SpringBootTest(properties = {
        "spring.cloud.nacos.discovery.enabled=false",
        "spring.cloud.discovery.enabled=false",
        "dispatch.auto.enabled=false",
        "dispatch.auto.claim-window-seconds=60"
})
@ActiveProfiles("test")
class DispatchTriggerServiceIntegrationTest {

    private static final int NORMAL_ORDER_ID = 99201;
    private static final int URGENT_ORDER_ID = 99202;

    @Autowired
    private DispatchTriggerService triggerService;

    @Autowired
    private JdbcTemplate jdbcTemplate;

    @Autowired
    private ObjectMapper objectMapper;

    @BeforeEach
    void setUp() {
        cleanRows();
        insertPendingOrder(NORMAL_ORDER_ID, "NORMAL");
        insertPendingOrder(URGENT_ORDER_ID, "URGENT");
    }

    @AfterEach
    void tearDown() {
        cleanRows();
    }

    @Test
    void normalApprovalOpensClaimWindowWithoutAutomaticEvent() {
        MaintainRecord order = load(NORMAL_ORDER_ID);

        DispatchTriggerService.ApprovalResult result = triggerService.approve(order, 1, true);

        assertTrue(result.updated());
        assertFalse(result.urgentTriggered());
        assertEquals("待领取", value("SELECT status FROM maintain_record WHERE id = ?", String.class, NORMAL_ORDER_ID));
        assertNotNull(value("SELECT claim_deadline FROM maintain_record WHERE id = ?", Date.class, NORMAL_ORDER_ID));
        assertEquals(0, countOutbox(NORMAL_ORDER_ID));
    }

    @Test
    void urgentApprovalCreatesExactlyOneOutboxEvent() throws Exception {
        MaintainRecord order = load(URGENT_ORDER_ID);

        DispatchTriggerService.ApprovalResult result = triggerService.approve(order, 1, true);

        assertTrue(result.updated());
        assertTrue(result.urgentTriggered());
        assertEquals(1, countOutbox(URGENT_ORDER_ID));
        assertEquals("urgent", value(
                "SELECT trigger_type FROM dispatch_event_outbox WHERE order_id = ?", String.class, URGENT_ORDER_ID));
        String payload = value("SELECT payload FROM dispatch_event_outbox WHERE order_id = ?",
                String.class, URGENT_ORDER_ID);
        JsonNode event = objectMapper.readTree(payload);
        assertEquals("urgent", event.path("trigger").asText());
        assertEquals("dispatch-request/v1", event.path("schema_version").asText());
    }

    @Test
    void repeatedTimeoutTriggerIsIdempotent() {
        triggerService.approve(load(NORMAL_ORDER_ID), 1, true);

        assertNotNull(triggerService.trigger(
                NORMAL_ORDER_ID, DispatchTriggerType.CLAIM_TIMEOUT, "deadline:fixed:v1"));
        assertNotNull(triggerService.trigger(
                NORMAL_ORDER_ID, DispatchTriggerType.CLAIM_TIMEOUT, "deadline:fixed:v1"));

        assertEquals(1, countOutbox(NORMAL_ORDER_ID));
        assertEquals("claim_timeout", value(
                "SELECT trigger_type FROM dispatch_event_outbox WHERE order_id = ?", String.class, NORMAL_ORDER_ID));
    }

    private void insertPendingOrder(int orderId, String priority) {
        jdbcTemplate.update("""
                INSERT INTO maintain_record
                  (id, device_id, tenant_id, maintenance_type, priority, status, version)
                VALUES (?, 99001, 'default', 'ELECTRICAL', ?, '待审批', 0)
                """, orderId, priority);
    }

    private MaintainRecord load(int orderId) {
        return jdbcTemplate.queryForObject("SELECT * FROM maintain_record WHERE id = ?", (rs, rowNum) -> {
            MaintainRecord order = new MaintainRecord();
            order.setId(rs.getInt("id"));
            order.setDeviceId(rs.getInt("device_id"));
            order.setTenantId(rs.getString("tenant_id"));
            order.setMaintenanceType(rs.getString("maintenance_type"));
            order.setPriority(rs.getString("priority"));
            order.setStatus(rs.getString("status"));
            order.setVersion(rs.getInt("version"));
            return order;
        }, orderId);
    }

    private int countOutbox(int orderId) {
        return value("SELECT COUNT(*) FROM dispatch_event_outbox WHERE order_id = ?", Integer.class, orderId);
    }

    private <T> T value(String sql, Class<T> type, Object argument) {
        return jdbcTemplate.queryForObject(sql, type, argument);
    }

    private void cleanRows() {
        jdbcTemplate.update("DELETE FROM dispatch_event_outbox WHERE order_id IN (?, ?)",
                NORMAL_ORDER_ID, URGENT_ORDER_ID);
        jdbcTemplate.update("DELETE FROM maintain_record WHERE id IN (?, ?)",
                NORMAL_ORDER_ID, URGENT_ORDER_ID);
    }
}
