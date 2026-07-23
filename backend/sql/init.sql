-- 装配式建筑构件全过程质量追溯平台 表结构（PostgreSQL）
-- 该文件作为 docker-compose 初始化脚本备份；运行时由 SQLAlchemy 自动 create_all 创建。

CREATE TABLE IF NOT EXISTS parties (
    id SERIAL PRIMARY KEY,
    code VARCHAR(32) UNIQUE NOT NULL,
    name VARCHAR(128) NOT NULL,
    role VARCHAR(32) NOT NULL,
    contact VARCHAR(64) DEFAULT '',
    address VARCHAR(256) DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(64) UNIQUE NOT NULL,
    password_hash VARCHAR(256) NOT NULL,
    full_name VARCHAR(64) NOT NULL,
    role VARCHAR(32) NOT NULL,
    party_id INTEGER REFERENCES parties(id),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS projects (
    id SERIAL PRIMARY KEY,
    code VARCHAR(64) UNIQUE NOT NULL,
    name VARCHAR(128) NOT NULL,
    location VARCHAR(256) DEFAULT '',
    owner_party_id INTEGER REFERENCES parties(id),
    contractor_party_id INTEGER REFERENCES parties(id),
    supervisor_party_id INTEGER REFERENCES parties(id),
    start_date TIMESTAMP,
    description TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS components (
    id SERIAL PRIMARY KEY,
    trace_code VARCHAR(64) UNIQUE NOT NULL,
    rfid_tag VARCHAR(64) DEFAULT '',
    project_id INTEGER REFERENCES projects(id),
    factory_id INTEGER REFERENCES parties(id),
    component_type VARCHAR(32) NOT NULL,
    spec VARCHAR(128) DEFAULT '',
    quantity INTEGER DEFAULT 1,
    mould_no VARCHAR(64) DEFAULT '',
    rebar_batch VARCHAR(64) DEFAULT '',
    concrete_ratio VARCHAR(64) DEFAULT '',
    pour_at TIMESTAMP,
    curing_record TEXT DEFAULT '',
    strength_report VARCHAR(128) DEFAULT '',
    embedded_parts JSON DEFAULT '{}'::jsonb,
    factory_inspection VARCHAR(16) DEFAULT '合格',
    current_stage VARCHAR(32) DEFAULT '已生产',
    qr_payload TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS factory_out_records (
    id SERIAL PRIMARY KEY,
    component_id INTEGER REFERENCES components(id),
    factory_id INTEGER REFERENCES parties(id),
    transport_party_id INTEGER REFERENCES parties(id),
    out_at TIMESTAMP NOT NULL,
    vehicle_no VARCHAR(32) NOT NULL,
    driver VARCHAR(32) NOT NULL,
    driver_phone VARCHAR(32) DEFAULT '',
    route_plan TEXT DEFAULT '',
    certificate_pdf VARCHAR(256) DEFAULT '',
    inspection_conclusion VARCHAR(16) DEFAULT '合格',
    UNIQUE(component_id)
);

CREATE TABLE IF NOT EXISTS transport_telemetry (
    id SERIAL PRIMARY KEY,
    component_id INTEGER REFERENCES components(id),
    transport_record_id INTEGER REFERENCES factory_out_records(id),
    reported_at TIMESTAMP NOT NULL,
    longitude DOUBLE PRECISION NOT NULL,
    latitude DOUBLE PRECISION NOT NULL,
    temperature DOUBLE PRECISION NOT NULL,
    humidity DOUBLE PRECISION NOT NULL,
    status VARCHAR(32) DEFAULT '运输中'
);

CREATE TABLE IF NOT EXISTS transport_alerts (
    id SERIAL PRIMARY KEY,
    component_id INTEGER REFERENCES components(id),
    telemetry_id INTEGER REFERENCES transport_telemetry(id),
    alert_type VARCHAR(32) NOT NULL,
    detail TEXT DEFAULT '',
    resolved BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS site_entry_records (
    id SERIAL PRIMARY KEY,
    component_id INTEGER REFERENCES components(id),
    contractor_id INTEGER REFERENCES parties(id),
    entered_at TIMESTAMP NOT NULL,
    stack_location VARCHAR(128) NOT NULL,
    inspector VARCHAR(64) NOT NULL,
    acceptance VARCHAR(16) NOT NULL,
    remark TEXT DEFAULT '',
    photo_urls JSON DEFAULT '[]'::jsonb,
    UNIQUE(component_id)
);

CREATE TABLE IF NOT EXISTS hoisting_records (
    id SERIAL PRIMARY KEY,
    component_id INTEGER REFERENCES components(id),
    contractor_id INTEGER REFERENCES parties(id),
    hoisted_at TIMESTAMP NOT NULL,
    equipment_no VARCHAR(64) NOT NULL,
    signal_worker VARCHAR(32) NOT NULL,
    rigger VARCHAR(32) NOT NULL,
    coord_lng DOUBLE PRECISION NOT NULL,
    coord_lat DOUBLE PRECISION NOT NULL,
    result VARCHAR(16) NOT NULL,
    UNIQUE(component_id)
);

CREATE TABLE IF NOT EXISTS joint_connections (
    id SERIAL PRIMARY KEY,
    component_id INTEGER REFERENCES components(id),
    contractor_id INTEGER REFERENCES parties(id),
    grout_at TIMESTAMP NOT NULL,
    grout_batch VARCHAR(64) NOT NULL,
    bedding_at TIMESTAMP,
    connection_type VARCHAR(32) NOT NULL,
    operator VARCHAR(32) NOT NULL,
    photo_urls JSON DEFAULT '[]'::jsonb,
    UNIQUE(component_id)
);

CREATE TABLE IF NOT EXISTS concealed_acceptances (
    id SERIAL PRIMARY KEY,
    component_id INTEGER REFERENCES components(id),
    supervisor_id INTEGER REFERENCES parties(id),
    accepted_at TIMESTAMP NOT NULL,
    quality_grade VARCHAR(16) NOT NULL,
    inspector VARCHAR(32) NOT NULL,
    photo_urls JSON DEFAULT '[]'::jsonb,
    video_url VARCHAR(256) DEFAULT '',
    conclusion TEXT DEFAULT '',
    UNIQUE(component_id)
);

CREATE TABLE IF NOT EXISTS protection_records (
    id SERIAL PRIMARY KEY,
    component_id INTEGER REFERENCES components(id),
    contractor_id INTEGER REFERENCES parties(id),
    decoration VARCHAR(128) DEFAULT '',
    mep VARCHAR(128) DEFAULT '',
    measures TEXT DEFAULT '',
    risk_warning TEXT DEFAULT '',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(component_id)
);

CREATE TABLE IF NOT EXISTS archive_packages (
    id SERIAL PRIMARY KEY,
    component_id INTEGER REFERENCES components(id),
    project_id INTEGER REFERENCES projects(id),
    owner_id INTEGER REFERENCES parties(id),
    archive_no VARCHAR(64) UNIQUE NOT NULL,
    file_path VARCHAR(256) NOT NULL,
    payload JSON DEFAULT '{}'::jsonb,
    status VARCHAR(16) DEFAULT '草稿',
    submitted_at TIMESTAMP,
    accepted_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(component_id)
);

CREATE TABLE IF NOT EXISTS offline_sync_logs (
    id SERIAL PRIMARY KEY,
    client_id VARCHAR(64) NOT NULL,
    batch_id VARCHAR(64) NOT NULL,
    payload JSON DEFAULT '{}'::jsonb,
    status VARCHAR(16) DEFAULT 'accepted',
    received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_components_factory ON components(factory_id);
CREATE INDEX IF NOT EXISTS idx_components_project ON components(project_id);
CREATE INDEX IF NOT EXISTS idx_components_stage ON components(current_stage);
CREATE INDEX IF NOT EXISTS idx_telemetry_reported ON transport_telemetry(reported_at);
CREATE INDEX IF NOT EXISTS idx_alerts_component ON transport_alerts(component_id);
CREATE INDEX IF NOT EXISTS idx_archive_status ON archive_packages(status);

-- 质监抽检 / 整改 / 维护 / 项目进度
CREATE TABLE IF NOT EXISTS quality_inspection_tasks (
    id SERIAL PRIMARY KEY,
    task_no VARCHAR(64) UNIQUE NOT NULL,
    component_id INTEGER REFERENCES components(id),
    project_id INTEGER REFERENCES projects(id),
    quality_party_id INTEGER REFERENCES parties(id),
    initiated_by INTEGER REFERENCES users(id),
    inspector_user_id INTEGER REFERENCES users(id),
    stage VARCHAR(32) NOT NULL,
    title VARCHAR(128) DEFAULT '',
    requirement TEXT DEFAULT '',
    planned_at TIMESTAMP,
    open_token VARCHAR(64) DEFAULT 'open',
    is_closed BOOLEAN DEFAULT FALSE,
    closed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(component_id, stage, open_token)
);
CREATE INDEX IF NOT EXISTS idx_qitask_component ON quality_inspection_tasks(component_id);
CREATE INDEX IF NOT EXISTS idx_qitask_project ON quality_inspection_tasks(project_id);
CREATE INDEX IF NOT EXISTS idx_qitask_open ON quality_inspection_tasks(is_closed);

CREATE TABLE IF NOT EXISTS quality_inspection_records (
    id SERIAL PRIMARY KEY,
    task_id INTEGER REFERENCES quality_inspection_tasks(id),
    component_id INTEGER REFERENCES components(id),
    inspector_user_id INTEGER REFERENCES users(id),
    sequence INTEGER DEFAULT 1,
    inspected_at TIMESTAMP NOT NULL,
    location VARCHAR(128) DEFAULT '',
    conclusion VARCHAR(16) NOT NULL,
    findings TEXT DEFAULT '',
    measures TEXT DEFAULT '',
    photo_urls JSON DEFAULT '[]'::jsonb,
    is_reinspection BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_qirec_task ON quality_inspection_records(task_id);
CREATE INDEX IF NOT EXISTS idx_qirec_time ON quality_inspection_records(inspected_at);

CREATE TABLE IF NOT EXISTS rectification_records (
    id SERIAL PRIMARY KEY,
    task_id INTEGER REFERENCES quality_inspection_tasks(id),
    component_id INTEGER REFERENCES components(id),
    contractor_party_id INTEGER REFERENCES parties(id),
    round INTEGER DEFAULT 1,
    status VARCHAR(16) DEFAULT '待整改',
    plan TEXT DEFAULT '',
    progress_note TEXT DEFAULT '',
    result_note TEXT DEFAULT '',
    photo_urls JSON DEFAULT '[]'::jsonb,
    deadline TIMESTAMP,
    submitted_at TIMESTAMP,
    closed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(task_id, round)
);
CREATE INDEX IF NOT EXISTS idx_rect_component ON rectification_records(component_id);
CREATE INDEX IF NOT EXISTS idx_rect_status ON rectification_records(status);

CREATE TABLE IF NOT EXISTS maintenance_check_records (
    id SERIAL PRIMARY KEY,
    component_id INTEGER REFERENCES components(id),
    project_id INTEGER REFERENCES projects(id),
    operator_party_id INTEGER REFERENCES parties(id),
    operator_user_id INTEGER REFERENCES users(id),
    checked_at TIMESTAMP NOT NULL,
    finding VARCHAR(16) NOT NULL,
    description TEXT DEFAULT '',
    action_taken TEXT DEFAULT '',
    next_check_in_days INTEGER DEFAULT 0,
    photo_urls JSON DEFAULT '[]'::jsonb,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_maint_component ON maintenance_check_records(component_id);
CREATE INDEX IF NOT EXISTS idx_maint_time ON maintenance_check_records(checked_at);

CREATE TABLE IF NOT EXISTS project_milestones (
    id SERIAL PRIMARY KEY,
    project_id INTEGER REFERENCES projects(id),
    code VARCHAR(32) NOT NULL,
    name VARCHAR(128) NOT NULL,
    stage VARCHAR(32) DEFAULT '已生产',
    planned_at TIMESTAMP,
    baseline_at TIMESTAMP,
    weight DOUBLE PRECISION DEFAULT 1.0,
    sort_no INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(project_id, code)
);
CREATE INDEX IF NOT EXISTS idx_milestone_project ON project_milestones(project_id);

CREATE TABLE IF NOT EXISTS component_locations (
    id SERIAL PRIMARY KEY,
    component_id INTEGER REFERENCES components(id),
    project_id INTEGER REFERENCES projects(id),
    longitude DOUBLE PRECISION NOT NULL,
    latitude DOUBLE PRECISION NOT NULL,
    building VARCHAR(64) DEFAULT '',
    floor VARCHAR(32) DEFAULT '',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(component_id)
);
CREATE INDEX IF NOT EXISTS idx_loc_project ON component_locations(project_id);
