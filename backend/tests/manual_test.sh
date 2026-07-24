#!/bin/bash
# ============================================================================
# AI 面试助手 - 后端手动测试脚本
# 使用方法: bash tests/manual_test.sh
# 前提: 后端服务已启动在 http://localhost:8000
# ============================================================================

BASE_URL="http://localhost:8000"
PASS=0
FAIL=0
TOTAL=0

# 颜色定义
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

check_status() {
    local test_name="$1"
    local expected_status="$2"
    local actual_status="$3"
    local response="$4"
    
    TOTAL=$((TOTAL + 1))
    if [ "$actual_status" -eq "$expected_status" ]; then
        echo -e "${GREEN}[PASS]${NC} $test_name (HTTP $actual_status)"
        PASS=$((PASS + 1))
    else
        echo -e "${RED}[FAIL]${NC} $test_name (期望 HTTP $expected_status, 实际 HTTP $actual_status)"
        echo "  响应: $(echo "$response" | head -c 200)"
        FAIL=$((FAIL + 1))
    fi
}

check_json_field() {
    local test_name="$1"
    local json="$2"
    local field="$3"
    local expected="$4"
    
    TOTAL=$((TOTAL + 1))
    local actual=$(echo "$json" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('$field', 'MISSING'))" 2>/dev/null)
    if [ "$actual" = "$expected" ]; then
        echo -e "${GREEN}[PASS]${NC} $test_name ($field=$actual)"
        PASS=$((PASS + 1))
    else
        echo -e "${RED}[FAIL]${NC} $test_name (期望 $field=$expected, 实际 $field=$actual)"
        FAIL=$((FAIL + 1))
    fi
}

echo "============================================"
echo "  AI 面试助手 后端测试"
echo "============================================"
echo ""

# ============================================================================
# 1. 基础端点测试
# ============================================================================
echo -e "${YELLOW}--- 1. 基础端点测试 ---${NC}"

# 根路径
RESPONSE=$(curl -s -w "\n%{http_code}" "$BASE_URL/")
STATUS=$(echo "$RESPONSE" | tail -1)
BODY=$(echo "$RESPONSE" | head -1)
check_status "GET / 返回 API 信息" 200 "$STATUS" "$BODY"

# 健康检查
RESPONSE=$(curl -s -w "\n%{http_code}" "$BASE_URL/health")
STATUS=$(echo "$RESPONSE" | tail -1)
BODY=$(echo "$RESPONSE" | head -1)
check_status "GET /health 健康检查" 200 "$STATUS" "$BODY"

echo ""

# ============================================================================
# 2. 会话管理测试
# ============================================================================
echo -e "${YELLOW}--- 2. 会话管理测试 ---${NC}"

# 创建会话
RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "$BASE_URL/api/sessions/" \
    -H "Content-Type: application/json" \
    -H "X-User-ID: test_user_001" \
    -d '{
        "mode": "mock",
        "title": "测试会话",
        "job_description": "Python后端工程师",
        "max_questions": 3
    }')
STATUS=$(echo "$RESPONSE" | tail -1)
BODY=$(echo "$RESPONSE" | head -1)
check_status "POST /api/sessions/ 创建会话" 200 "$STATUS" "$BODY"

# 提取 session_id
SESSION_ID=$(echo "$BODY" | python3 -c "import sys,json; print(json.load(sys.stdin).get('session',{}).get('session_id',''))" 2>/dev/null)
if [ -n "$SESSION_ID" ]; then
    echo -e "  会话ID: $SESSION_ID"
fi

# 获取会话列表（带 user_id）
RESPONSE=$(curl -s -w "\n%{http_code}" "$BASE_URL/api/sessions/?limit=10" \
    -H "X-User-ID: test_user_001")
STATUS=$(echo "$RESPONSE" | tail -1)
BODY=$(echo "$RESPONSE" | head -1)
check_status "GET /api/sessions/ 获取会话列表" 200 "$STATUS" "$BODY"

# 测试跨用户访问控制（Critical Issue C1）
RESPONSE=$(curl -s -w "\n%{http_code}" "$BASE_URL/api/sessions/$SESSION_ID" \
    -H "X-User-ID: other_user_999")
STATUS=$(echo "$RESPONSE" | tail -1)
BODY=$(echo "$RESPONSE" | head -1)
check_status "跨用户访问会话应返回404" 404 "$STATUS" "$BODY"

# 获取会话详情
RESPONSE=$(curl -s -w "\n%{http_code}" "$BASE_URL/api/sessions/$SESSION_ID" \
    -H "X-User-ID: test_user_001")
STATUS=$(echo "$RESPONSE" | tail -1)
BODY=$(echo "$RESPONSE" | head -1)
check_status "GET /api/sessions/{id} 获取会话详情" 200 "$STATUS" "$BODY"

# 删除不存在的会话
RESPONSE=$(curl -s -w "\n%{http_code}" -X DELETE "$BASE_URL/api/sessions/nonexistent-id" \
    -H "X-User-ID: test_user_001")
STATUS=$(echo "$RESPONSE" | tail -1)
BODY=$(echo "$RESPONSE" | head -1)
check_status "DELETE /api/sessions/{id} 删除不存在的会话返回404" 404 "$STATUS" "$BODY"

echo ""

# ============================================================================
# 3. 文件上传测试
# ============================================================================
echo -e "${YELLOW}--- 3. 文件上传测试 ---${NC}"

# 创建测试简历文件
echo "张三 | Python工程师 | 3年经验" > /tmp/test_resume.txt

# 上传简历
RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "$BASE_URL/api/upload/resume" \
    -F "file=@/tmp/test_resume.txt")
STATUS=$(echo "$RESPONSE" | tail -1)
BODY=$(echo "$RESPONSE" | head -1)
check_status "POST /api/upload/resume 上传简历" 200 "$STATUS" "$BODY"

# 清理
rm -f /tmp/test_resume.txt

# 伪装成 PDF 的非法文件应被拒绝
echo "not a real pdf" > /tmp/fake_resume.pdf
RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "$BASE_URL/api/upload/resume" \
    -F "file=@/tmp/fake_resume.pdf")
STATUS=$(echo "$RESPONSE" | tail -1)
BODY=$(echo "$RESPONSE" | head -1)
check_status "POST /api/upload/resume 伪造PDF应返回400" 400 "$STATUS" "$BODY"
rm -f /tmp/fake_resume.pdf

echo ""

# ============================================================================
# 4. API 配置验证测试
# ============================================================================
echo -e "${YELLOW}--- 4. API 配置验证测试 ---${NC}"

# 无效 API Key
RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "$BASE_URL/api/config/validate" \
    -H "Content-Type: application/json" \
    -d '{
        "api_key": "invalid-key",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "gpt-4"
    }')
STATUS=$(echo "$RESPONSE" | tail -1)
BODY=$(echo "$RESPONSE" | head -1)
check_status "POST /api/config/validate 无效Key返回200(success=false)" 200 "$STATUS" "$BODY"
check_json_field "验证结果为失败" "$BODY" "success" "False"

echo ""

# ============================================================================
# 5. 题库测试
# ============================================================================
echo -e "${YELLOW}--- 5. 题库测试 ---${NC}"

# 创建题库条目
RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "$BASE_URL/api/question-bank/items" \
    -H "Content-Type: application/json" \
    -H "X-User-ID: test_user_001" \
    -d '{
        "question_text": "什么是Python的GIL？",
        "reference_answer": "GIL是Global Interpreter Lock的缩写",
        "tags": ["python", "并发"],
        "difficulty": "medium",
        "question_type": "tech"
    }')
STATUS=$(echo "$RESPONSE" | tail -1)
BODY=$(echo "$RESPONSE" | head -1)
check_status "POST /api/question-bank/items 创建题目" 200 "$STATUS" "$BODY"

# 获取题库列表
RESPONSE=$(curl -s -w "\n%{http_code}" "$BASE_URL/api/question-bank/items?limit=10" \
    -H "X-User-ID: test_user_001")
STATUS=$(echo "$RESPONSE" | tail -1)
BODY=$(echo "$RESPONSE" | head -1)
check_status "GET /api/question-bank/items 列出题目" 200 "$STATUS" "$BODY"

# 测试负索引（Bug Fix 验证）
if [ -n "$SESSION_ID" ]; then
    RESPONSE=$(curl -s -w "\n%{http_code}" -X POST \
        "$BASE_URL/api/question-bank/save-from-session?session_id=$SESSION_ID&question_index=-1" \
        -H "X-User-ID: test_user_001")
    STATUS=$(echo "$RESPONSE" | tail -1)
    BODY=$(echo "$RESPONSE" | head -1)
    # 应该返回 404（题目不存在），而不是保存最后一题
    check_status "save-from-session 负索引应返回404" 404 "$STATUS" "$BODY"
fi

echo ""

# ============================================================================
# 6. 投递追踪测试
# ============================================================================
echo -e "${YELLOW}--- 6. 投递追踪测试 ---${NC}"

# 创建投递记录
RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "$BASE_URL/api/applications/" \
    -H "Content-Type: application/json" \
    -H "X-User-ID: test_user_001" \
    -d '{
        "company_name": "测试公司",
        "position_title": "Python工程师",
        "status": "applied"
    }')
STATUS=$(echo "$RESPONSE" | tail -1)
BODY=$(echo "$RESPONSE" | head -1)
check_status "POST /api/applications/ 创建投递记录" 200 "$STATUS" "$BODY"

# 提取 application_id
APP_ID=$(echo "$BODY" | python3 -c "import sys,json; print(json.load(sys.stdin).get('application',{}).get('id',''))" 2>/dev/null)

# 获取投递列表
RESPONSE=$(curl -s -w "\n%{http_code}" "$BASE_URL/api/applications/?limit=10" \
    -H "X-User-ID: test_user_001")
STATUS=$(echo "$RESPONSE" | tail -1)
BODY=$(echo "$RESPONSE" | head -1)
check_status "GET /api/applications/ 获取投递列表" 200 "$STATUS" "$BODY"

# 添加事件
if [ -n "$APP_ID" ]; then
    RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "$BASE_URL/api/applications/$APP_ID/events" \
        -H "Content-Type: application/json" \
        -H "X-User-ID: test_user_001" \
        -d '{
            "event_type": "interview",
            "note": "一面通过"
        }')
    STATUS=$(echo "$RESPONSE" | tail -1)
    BODY=$(echo "$RESPONSE" | head -1)
    check_status "POST /api/applications/{id}/events 添加事件" 200 "$STATUS" "$BODY"
fi

echo ""

# ============================================================================
# 7. 简历工具测试（需要有效的 API 配置）
# ============================================================================
echo -e "${YELLOW}--- 7. 简历工具测试（需要 API Key）---${NC}"

# 获取已完成会话列表
RESPONSE=$(curl -s -w "\n%{http_code}" "$BASE_URL/api/resume/sessions?limit=5" \
    -H "X-User-ID: test_user_001")
STATUS=$(echo "$RESPONSE" | tail -1)
BODY=$(echo "$RESPONSE" | head -1)
check_status "GET /api/resume/sessions 获取已完成会话" 200 "$STATUS" "$BODY"

# 获取简历分析历史
RESPONSE=$(curl -s -w "\n%{http_code}" "$BASE_URL/api/resume/results?limit=5" \
    -H "X-User-ID: test_user_001")
STATUS=$(echo "$RESPONSE" | tail -1)
BODY=$(echo "$RESPONSE" | head -1)
check_status "GET /api/resume/results 获取分析历史" 200 "$STATUS" "$BODY"

# 获取素材列表
RESPONSE=$(curl -s -w "\n%{http_code}" "$BASE_URL/api/resume/materials?limit=5" \
    -H "X-User-ID: test_user_001")
STATUS=$(echo "$RESPONSE" | tail -1)
BODY=$(echo "$RESPONSE" | head -1)
check_status "GET /api/resume/materials 获取素材列表" 200 "$STATUS" "$BODY"

echo ""

# ============================================================================
# 8. 错误处理测试
# ============================================================================
echo -e "${YELLOW}--- 8. 错误处理测试 ---${NC}"

# 不存在的端点
RESPONSE=$(curl -s -w "\n%{http_code}" "$BASE_URL/api/nonexistent")
STATUS=$(echo "$RESPONSE" | tail -1)
check_status "GET /api/nonexistent 返回404" 404 "$STATUS" ""

# 空消息聊天
RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "$BASE_URL/api/chat/stream" \
    -H "Content-Type: application/json" \
    -d '{
        "message": "",
        "thread_id": "test",
        "mode": "mock",
        "resume_context": "test",
        "job_description": "test"
    }')
STATUS=$(echo "$RESPONSE" | tail -1)
check_status "POST /api/chat/stream 空消息返回400" 400 "$STATUS" ""

echo ""

# ============================================================================
# 9. 清理测试数据
# ============================================================================
echo -e "${YELLOW}--- 9. 清理测试数据 ---${NC}"

# 删除会话
if [ -n "$SESSION_ID" ]; then
    RESPONSE=$(curl -s -w "\n%{http_code}" -X DELETE "$BASE_URL/api/sessions/$SESSION_ID" \
        -H "X-User-ID: test_user_001")
    STATUS=$(echo "$RESPONSE" | tail -1)
    check_status "DELETE 清理测试会话" 200 "$STATUS" ""
fi

echo ""

# ============================================================================
# 测试结果汇总
# ============================================================================
echo "============================================"
echo -e "  测试结果汇总"
echo "============================================"
echo -e "  总计: $TOTAL"
echo -e "  ${GREEN}通过: $PASS${NC}"
echo -e "  ${RED}失败: $FAIL${NC}"
echo "============================================"

if [ $FAIL -eq 0 ]; then
    echo -e "${GREEN}所有测试通过！${NC}"
    exit 0
else
    echo -e "${RED}有 $FAIL 个测试失败${NC}"
    exit 1
fi
