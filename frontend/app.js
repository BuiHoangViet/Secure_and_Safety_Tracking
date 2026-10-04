document.addEventListener('DOMContentLoaded', () => {
    // UI Elements
    const timeEl = document.getElementById('current-time');
    const settingsBtn = document.querySelector('button.settings-btn');
    const serverStatusText = document.querySelector('.status-text');
    const serverStatusIndicator = document.querySelector('.status-indicator');
    
    const alertWarning = document.getElementById('alert-warning');
    const alertSafe = document.getElementById('alert-safe');
    
    const attrGender = document.getElementById('attr-gender');
    const attrAge = document.getElementById('attr-age');
    const attrHeight = document.getElementById('attr-height');
    const attrUpper = document.getElementById('attr-upper');
    const attrLower = document.getElementById('attr-lower');
    const attrFootwear = document.getElementById('attr-footwear');
    
    const rowUpper = document.getElementById('row-upper');
    const rowLower = document.getElementById('row-lower');
    const rowFootwear = document.getElementById('row-footwear');
    
    const accessoriesCount = document.getElementById('accessories-count');
    const accessoriesList = document.getElementById('accessories-list');
    
    const riskBox = document.getElementById('risk-box');
    const riskLevel = document.getElementById('risk-level');
    const riskReasonContainer = document.getElementById('risk-reason-container');
    const dangerSignsList = document.getElementById('danger-signs-list');
    const targetBox = document.getElementById('target-box');

    const fpsVal = document.getElementById('fps-val');
    const resVal = document.getElementById('res-val');
    const personsVal = document.getElementById('persons-val');
    const engineStatus = document.getElementById('engine-status');
    const analysisText = document.getElementById('analysis-text');
    const videoContainer = document.querySelector('.video-container');
    const videoFeed = document.getElementById('video-feed-el');
    const uploadInput = document.getElementById('upload-input');  // only on upload.html

    // State Variables
    let isDemoMode = false;
    let demoStep = 0;
    let pollInterval = null;

    // Data source: laptop backend API (backend/server.py) by default.
    // ?file=testcase.json switches back to reading a static JSON file.
    const urlParams = new URLSearchParams(window.location.search);
    const fileParam = urlParams.get('file');
    const targetFile = fileParam || 'current_attributes.json';
    let useApi = !fileParam;

    // Translations Dictionary
    const TRANSLATIONS = {
        gender: {
            personalMale: "Nam",
            personalFemale: "Nữ"
        },
        age: {
            personalLess15: "Dưới 15 tuổi",
            personalLess30: "25-30",
            personalLess45: "30-45",
            personalLess60: "45-60",
            personalLarger60: "Trên 60 tuổi"
        },
        mask: {
            maskNone: "Không",
            maskSurgical: "Khẩu trang y tế",
            maskClothN95: "Khẩu trang N95 / vải"
        },
        glasses: {
            glassesNone: "Không",
            glassesEyeglasses: "Kính thuốc",
            glassesSunglasses: "Kính râm",
            glassesOthers: "Kính khác"
        },
        hatStyle: {
            hatCap: "Mũ lưỡi trai",
            hatBeanie: "Mũ len",
            hatHelmet: "Mũ bảo hiểm",
            hatOthers: "Mũ khác"
        },
        hatColor: {
            hatBlack: "đen",
            hatGrey: "xám",
            hatWhite: "trắng",
            hatBrown: "nâu",
            hatRed: "đỏ",
            hatPink: "hồng",
            hatYellow: "vàng",
            hatOrange: "cam",
            hatGreen: "xanh lá",
            hatBlue: "xanh",
            hatPurple: "tím"
        },
        accessory: {
            accessoryMuffler: "Khăn quàng cổ",
            accessoryKerchief: "Khăn trùm đầu/cổ",
            accessoryHeadphone: "Tai nghe",
            accessoryHairBand: "Băng đô / Cài tóc"
        },
        carrying: {
            carryingBackpack: "Balo",
            carryingOther: "Túi xách khác",
            carryingMessengerBag: "Túi đeo chéo",
            carryingPlasticBags: "Túi nilon",
            carryingBabyBuggy: "Xe nôi em bé",
            carryingShoppingTro: "Xe đẩy siêu thị",
            carryingUmbrella: "Ô / Dù",
            carryingFolder: "Bìa hồ sơ / Tài liệu",
            carryingLuggageCase: "Vali kéo",
            carryingSuitcase: "Vali / Cặp xách"
        },
        upperStyle: {
            upperBodyShortSleeve: "Áo ngắn tay",
            upperBodyLongSleeve: "Áo dài tay",
            upperBodyCasual: "Áo thường phục",
            upperBodyFormal: "Áo công sở",
            upperBodyJacket: "Áo khoác",
            upperBodyLogo: "Áo thun có logo",
            upperBodyPlaid: "Áo kẻ caro",
            upperBodyThinStripes: "Áo sọc mảnh",
            upperBodyTshirt: "Áo thun",
            upperBodyOther: "Áo khác",
            upperBodyVNeck: "Áo cổ chữ V",
            upperBodyNoSleeve: "Áo ba lỗ/sát nách",
            upperBodySuit: "Áo vest",
            upperBodySweater: "Áo hoodie",
            upperBodyThickStripes: "Áo sọc dày"
        },
        upperColor: {
            upperBodyBlack: "đen",
            upperBodyGrey: "xám",
            upperBodyWhite: "trắng",
            upperBodyBrown: "nâu",
            upperBodyRed: "đỏ",
            upperBodyPink: "hồng",
            upperBodyYellow: "vàng",
            upperBodyOrange: "cam",
            upperBodyGreen: "xanh lá",
            upperBodyBlue: "xanh",
            upperBodyPurple: "tím"
        },
        lowerStyle: {
            lowerBodyShorts: "Quần đùi/short",
            lowerBodyTrousers: "Quần dài",
            lowerBodyShortSkirt: "Chân váy ngắn",
            lowerBodyLongSkirt: "Chân váy dài",
            lowerBodyCasual: "Quần thường phục",
            lowerBodyFormal: "Quần âu/tây",
            lowerBodyJeans: "Quần jean",
            lowerBodyCapri: "Quần lửng",
            lowerBodyHotPants: "Quần ngắn ôm",
            lowerBodyPlaid: "Quần kẻ caro",
            lowerBodyThinStripes: "Quần sọc",
            lowerBodySuits: "Quần bộ vest"
        },
        lowerColor: {
            lowerBodyBlack: "đen",
            lowerBodyGrey: "xám",
            lowerBodyWhite: "trắng",
            lowerBodyBrown: "nâu",
            lowerBodyRed: "đỏ",
            lowerBodyPink: "hồng",
            lowerBodyYellow: "vàng",
            lowerBodyOrange: "cam",
            lowerBodyGreen: "xanh lá",
            lowerBodyBlue: "xanh đậm",
            lowerBodyPurple: "tím"
        },
        footwearStyle: {
            footwearShoes: "Giày",
            footwearLeatherShoes: "Giày da",
            footwearSandals: "Dép xăng-đan",
            footwearSneaker: "Giày thể thao",
            footwearBoots: "Ủng/Bốt",
            footwearStocking: "Tất/Vớ"
        },
        footwearColor: {
            footwearBlack: "đen",
            footwearGrey: "xám",
            footwearWhite: "trắng",
            footwearBrown: "nâu",
            footwearRed: "đỏ",
            footwearPink: "hồng",
            footwearYellow: "vàng",
            footwearOrange: "cam",
            footwearGreen: "xanh lá",
            footwearBlue: "xanh",
            footwearPurple: "tím"
        },
        // Extra cues from the laptop backend (CLIP head-crop checks + context)
        cues: {
            hoodUp: "Kéo mũ trùm đầu (hoodie)",
            faceCovered: "Trùm kín mặt (mặt nạ / khăn)",
            fullFaceHelmet: "Mũ bảo hiểm kín mặt",
            faceConcealedHigh: "Mức che mặt tổng hợp cao",
            loitering: "Lảng vảng lâu trước camera",
            avoidingCamera: "Liên tục né / quay lưng camera",
            groupConcealed: "Nhiều người cùng che mặt",
            // Behaviour (pose keypoints + tracking)
            handsCoveringFace: "Dùng tay che mặt",
            lookingAround: "Liên tục nhìn ngó xung quanh",
            hidingFaceDown: "Cúi gằm mặt né camera",
            armsRaised: "Giơ / vung tay",
            running: "Chạy / di chuyển rất nhanh",
            fastApproach: "Lao nhanh về phía camera",
            pacing: "Đi tới đi lui nhiều lần",
            edgeLurking: "Nấp ở mép khung hình",
            wearingGloves: "Đeo găng tay",
            cameraOcclusion: "Camera bị che / mất hình"
        },
        // Objects detected by YOLO near the person
        weapons: {
            weaponKnife: "Dao",
            weaponBat: "Gậy",
            weaponScissors: "Kéo",
            weaponGun: "Súng"
        }
    };

    const RISK_TEXT = { "High": "CAO", "Medium-High": "TRUNG BÌNH CAO", "Medium": "TRUNG BÌNH", "Low": "THẤP" };

    // Full 15 Rules from dangerous_attributes_rules.csv
    const DANGER_RULES = [
        { id: 1, conditions: ["maskSurgical", "glassesSunglasses", "hatCap"], category: "Full Face Concealment", risk: "High", desc: "Che kín mặt hoàn toàn (Khẩu trang y tế + Kính râm + Mũ lưỡi trai)" },
        { id: 2, conditions: ["maskClothN95", "glassesSunglasses", "hatCap"], category: "Full Face Concealment", risk: "High", desc: "Che kín mặt hoàn toàn (Khẩu trang N95/vải + Kính râm + Mũ lưỡi trai)" },
        { id: 3, conditions: ["maskSurgical", "glassesSunglasses", "hatBeanie"], category: "Full Face Concealment", risk: "High", desc: "Che kín mặt (Khẩu trang y tế + Kính râm + Mũ len)" },
        { id: 4, conditions: ["maskClothN95", "glassesSunglasses", "hatBeanie"], category: "Full Face Concealment", risk: "High", desc: "Che kín mặt (Khẩu trang N95/vải + Kính râm + Mũ len)" },
        { id: 5, conditions: ["maskSurgical", "glassesSunglasses", "hatHelmet"], category: "Suspicious Helmet & Mask", risk: "High", desc: "Đội mũ bảo hiểm kết hợp khẩu trang y tế và kính râm che diện mạo" },
        { id: 6, conditions: ["maskClothN95", "glassesSunglasses", "hatHelmet"], category: "Suspicious Helmet & Mask", risk: "High", desc: "Đội mũ bảo hiểm kết hợp khẩu trang N95/vải và kính râm che diện mạo" },
        { id: 7, conditions: ["maskSurgical", "accessoryMuffler", "hatCap"], category: "Face Concealment with Muffler", risk: "Medium-High", desc: "Che mặt bằng Khẩu trang y tế + Khăn quàng cổ + Mũ lưỡi trai" },
        { id: 8, conditions: ["maskClothN95", "accessoryMuffler", "hatCap"], category: "Face Concealment with Muffler", risk: "Medium-High", desc: "Che mặt bằng Khẩu trang N95/vải + Khăn quàng cổ + Mũ lưỡi trai" },
        { id: 9, conditions: ["maskSurgical", "accessoryKerchief", "glassesSunglasses"], category: "Face Concealment with Kerchief", risk: "Medium-High", desc: "Khăn trùm đầu/cổ + Khẩu trang y tế + Kính râm" },
        { id: 10, conditions: ["maskClothN95", "accessoryKerchief", "glassesSunglasses"], category: "Face Concealment with Kerchief", risk: "Medium-High", desc: "Khăn trùm đầu/cổ + Khẩu trang N95/vải + Kính râm" },
        { id: 11, conditions: ["maskSurgical", "glassesSunglasses", "upperBodyJacket", "upperBodyBlack"], category: "Dark Concealed Outfit", risk: "High", desc: "Trang phục đen ngụy trang (Áo khoác đen + Khẩu trang y tế + Kính râm)" },
        { id: 12, conditions: ["maskClothN95", "glassesSunglasses", "upperBodyJacket", "upperBodyBlack"], category: "Dark Concealed Outfit", risk: "High", desc: "Trang phục đen ngụy trang (Áo khoác đen + Khẩu trang N95/vải + Kính râm)" },
        { id: 13, conditions: ["maskSurgical", "hatCap", "carryingLuggageCase"], category: "Suspicious Luggage & Concealment", risk: "Medium-High", desc: "Mang hành lý/vali nguy vấn + Che mặt (Khẩu trang y tế + Mũ lưỡi trai)" },
        { id: 14, conditions: ["maskClothN95", "hatCap", "carryingSuitcase"], category: "Suspicious Luggage & Concealment", risk: "Medium-High", desc: "Mang vali nghi vấn + Che mặt (Khẩu trang N95/vải + Mũ lưỡi trai)" },
        { id: 15, conditions: ["glassesSunglasses", "hatCap", "accessoryMuffler"], category: "Partial Face Concealment", risk: "Medium", desc: "Che phủ khuôn mặt không có khẩu trang (Kính râm + Mũ lưỡi trai + Khăn quàng cổ)" }
    ];

    // Evaluate danger rules against active labels
    function evaluateDangerousRules(labels) {
        const matchedRules = [];
        const dangerousLabelsSet = new Set();

        DANGER_RULES.forEach(rule => {
            const isMatch = rule.conditions.every(cond => labels.includes(cond));
            if (isMatch) {
                matchedRules.push(rule);
                rule.conditions.forEach(cond => dangerousLabelsSet.add(cond));
            }
        });

        // Weapon detection
        const weaponLabels = labels.filter(l => 
            l.toLowerCase().includes("weapon") || 
            l.toLowerCase().includes("gun") || 
            l.toLowerCase().includes("knife")
        );
        if (weaponLabels.length > 0) {
            matchedRules.push({
                id: 99,
                category: "Threat Item",
                risk: "High",
                desc: `Phát hiện hung khí nguy hiểm (${weaponLabels.join(", ")})`
            });
            weaponLabels.forEach(l => dangerousLabelsSet.add(l));
        }

        // Fallback rule: Mask + (Hoodie / Jacket / Hat)
        const hasMask = labels.some(l => l === "maskClothN95" || l === "maskSurgical");
        const hasHoodie = labels.includes("upperBodySweater");
        const hasJacket = labels.includes("upperBodyJacket");
        const hasHat = labels.some(l => ["hatCap", "hatBeanie", "hatOthers", "hatHelmet"].includes(l));

        if (matchedRules.length === 0 && hasMask && (hasHoodie || hasJacket || hasHat)) {
            const items = [];
            if (hasHoodie) items.push("Áo hoodie");
            if (hasJacket) items.push("Áo khoác");
            if (hasHat) items.push("Mũ");
            const maskType = labels.includes("maskClothN95") ? "che kín mặt" : "y tế";
            matchedRules.push({
                id: 98,
                category: "Concealment",
                risk: "High",
                desc: `Đeo khẩu trang (${maskType}) kết hợp trùm đầu / đội mũ (${items.join(", ")})`
            });
            if (labels.includes("maskClothN95")) dangerousLabelsSet.add("maskClothN95");
            if (labels.includes("maskSurgical")) dangerousLabelsSet.add("maskSurgical");
            if (hasHoodie) dangerousLabelsSet.add("upperBodySweater");
            if (hasJacket) dangerousLabelsSet.add("upperBodyJacket");
            ["hatCap", "hatBeanie", "hatOthers", "hatHelmet"].forEach(h => {
                if (labels.includes(h)) dangerousLabelsSet.add(h);
            });
        }

        return { matchedRules, dangerousLabelsSet };
    }

    // Extract all accessories & detected items from backend output
    function extractDetectedAccessories(labels) {
        const items = [];

        // 1. Hat / Headwear
        const hatTypeKey = labels.find(l => TRANSLATIONS.hatStyle[l]);
        if (hatTypeKey) {
            const hatName = TRANSLATIONS.hatStyle[hatTypeKey];
            const hatColorKey = labels.find(l => TRANSLATIONS.hatColor[l]);
            const colorName = hatColorKey ? TRANSLATIONS.hatColor[hatColorKey] : "";
            items.push({
                type: 'hat',
                key: hatTypeKey,
                colorKey: hatColorKey,
                label: "Mũ / Nón",
                value: colorName ? `${hatName} (${colorName})` : hatName
            });
        }

        // 2. Mask
        const maskKey = labels.find(l => TRANSLATIONS.mask[l] && l !== "maskNone");
        if (maskKey) {
            items.push({
                type: 'mask',
                key: maskKey,
                label: "Khẩu trang",
                value: TRANSLATIONS.mask[maskKey]
            });
        }

        // 3. Glasses
        const glassesKey = labels.find(l => TRANSLATIONS.glasses[l] && l !== "glassesNone");
        if (glassesKey) {
            items.push({
                type: 'glasses',
                key: glassesKey,
                label: "Kính mắt",
                value: TRANSLATIONS.glasses[glassesKey]
            });
        }

        // 4. Personal Accessories
        labels.forEach(l => {
            if (TRANSLATIONS.accessory[l] && l !== "accessoryNothing") {
                items.push({
                    type: 'accessory',
                    key: l,
                    label: "Phụ kiện",
                    value: TRANSLATIONS.accessory[l]
                });
            }
        });

        // 5. Carrying items
        labels.forEach(l => {
            if (TRANSLATIONS.carrying[l] && l !== "carryingNothing") {
                items.push({
                    type: 'carrying',
                    key: l,
                    label: "Vật dụng mang theo",
                    value: TRANSLATIONS.carrying[l]
                });
            }
        });

        // 6. Weapons / Threat items
        labels.forEach(l => {
            if (l.toLowerCase().includes("weapon") || l.toLowerCase().includes("gun") || l.toLowerCase().includes("knife")) {
                items.push({
                    type: 'weapon',
                    key: l,
                    label: "Hung khí / Vật nghi vấn",
                    value: `Phát hiện vật nguy hiểm (${TRANSLATIONS.weapons[l] || l})`
                });
            }
        });

        // 7. Behaviour / concealment cues
        labels.forEach(l => {
            if (TRANSLATIONS.cues[l]) {
                items.push({
                    type: 'cue',
                    key: l,
                    label: "Dấu hiệu",
                    value: TRANSLATIONS.cues[l]
                });
            }
        });

        return items;
    }

    // Helper to get value by keys
    function getValueByKeys(labelsList, translationGroup) {
        for (const key of labelsList) {
            if (translationGroup[key]) {
                return translationGroup[key];
            }
        }
        return null;
    }

    // Live Clock Update
    function updateClock() {
        const now = new Date();
        const day = String(now.getDate()).padStart(2, '0');
        const month = String(now.getMonth() + 1).padStart(2, '0');
        const year = now.getFullYear();
        const hours = String(now.getHours()).padStart(2, '0');
        const minutes = String(now.getMinutes()).padStart(2, '0');
        const seconds = String(now.getSeconds()).padStart(2, '0');
        
        timeEl.textContent = `${day}/${month}/${year} ${hours}:${minutes}:${seconds}`;
    }
    setInterval(updateClock, 1000);
    updateClock();

    // Lucide Icons
    function initIcons() {
        if (window.lucide) {
            window.lucide.createIcons();
        }
    }
    initIcons();

    // Update UI Elements with attributes
    // serverDanger (optional): rule result computed by the backend from dangerous_attributes_rules.csv
    function updateUI(labels, serverDanger) {
        if (!labels || labels.length === 0) {
            resetUI();
            return;
        }

        // 1. Gender & Age
        const gender = getValueByKeys(labels, TRANSLATIONS.gender) || "Chưa xác định";
        const age = getValueByKeys(labels, TRANSLATIONS.age) || "Chưa xác định";
        attrGender.textContent = gender;
        attrAge.textContent = age;

        let heightStr = "~175cm";
        if (gender === "Nữ") {
            heightStr = "~162cm";
        } else if (labels.includes("personalLess15")) {
            heightStr = "~145cm";
        }
        attrHeight.textContent = heightStr;

        // 2. Upper clothing
        const upperStyle = getValueByKeys(labels, TRANSLATIONS.upperStyle);
        const upperColor = getValueByKeys(labels, TRANSLATIONS.upperColor);
        let upperText = "Chưa có dữ liệu";
        if (upperStyle && upperColor) {
            upperText = `${upperStyle} màu ${upperColor}`;
        } else if (upperStyle) {
            upperText = upperStyle;
        } else if (upperColor) {
            upperText = `Áo màu ${upperColor}`;
        }
        attrUpper.textContent = upperText;

        // 3. Lower clothing
        const lowerStyle = getValueByKeys(labels, TRANSLATIONS.lowerStyle);
        const lowerColor = getValueByKeys(labels, TRANSLATIONS.lowerColor);
        let lowerText = "Chưa có dữ liệu";
        if (lowerStyle && lowerColor) {
            lowerText = `${lowerStyle} màu ${lowerColor}`;
        } else if (lowerStyle) {
            lowerText = lowerStyle;
        } else if (lowerColor) {
            lowerText = `Quần màu ${lowerColor}`;
        }
        attrLower.textContent = lowerText;

        // 4. Footwear
        const footwearStyle = getValueByKeys(labels, TRANSLATIONS.footwearStyle);
        const footwearColor = getValueByKeys(labels, TRANSLATIONS.footwearColor);
        let footwearText = "Chưa có dữ liệu";
        if (footwearStyle && footwearColor) {
            footwearText = `${footwearStyle} màu ${footwearColor}`;
        } else if (footwearStyle) {
            footwearText = footwearStyle;
        }
        attrFootwear.textContent = footwearText;

        // 5. Evaluate Dangerous Rules
        const { matchedRules, dangerousLabelsSet } = serverDanger
            ? { matchedRules: serverDanger.matched_rules || [], dangerousLabelsSet: new Set(serverDanger.danger_labels || []) }
            : evaluateDangerousRules(labels);

        // Highlight Upper clothing if dangerous
        if (labels.some(l => (l === "upperBodyJacket" || l === "upperBodySweater" || l === "upperBodyBlack") && dangerousLabelsSet.has(l))) {
            rowUpper.classList.add('suspicious');
        } else {
            rowUpper.classList.remove('suspicious');
        }

        // Highlight Lower clothing if dangerous
        if (labels.some(l => dangerousLabelsSet.has(l) && l.startsWith("lowerBody"))) {
            rowLower.classList.add('suspicious');
        } else {
            rowLower.classList.remove('suspicious');
        }

        // 6. Dynamic Rendering for PHỤ KIỆN & VẬT DỤNG
        const detectedAccessories = extractDetectedAccessories(labels);
        accessoriesCount.textContent = `${detectedAccessories.length} phát hiện`;
        accessoriesList.innerHTML = '';

        if (detectedAccessories.length === 0) {
            accessoriesList.innerHTML = `
                <div class="empty-accessories-state">
                    <span>Không phát hiện phụ kiện / vật dụng</span>
                </div>
            `;
        } else {
            detectedAccessories.forEach(item => {
                const isItemDangerous = dangerousLabelsSet.has(item.key) || 
                                         (item.colorKey && dangerousLabelsSet.has(item.colorKey)) ||
                                         item.type === 'weapon';

                const itemRow = document.createElement('div');
                itemRow.className = `attribute-row ${isItemDangerous ? 'suspicious' : ''}`;
                
                itemRow.innerHTML = `
                    <span class="attr-label">${item.label}</span>
                    <span class="attr-value ${isItemDangerous ? 'bold-red-text' : ''}">
                        ${item.value}
                    </span>
                `;
                accessoriesList.appendChild(itemRow);
            });
        }

        // 7. Update Risk Assessment & Dangerous Signs Display (Printed in Bold Red Text)
        if (matchedRules.length > 0) {
            // High Risk State
            alertWarning.style.display = 'flex';
            alertSafe.style.display = 'none';
            const alertTextContainer = alertWarning.querySelector('.alert-content p');
            if (alertTextContainer) {
                alertTextContainer.textContent = "Phát hiện nguy hiểm!";
            }
            
            riskBox.className = 'risk-assessment-section high-risk';
            if (serverDanger) {
                // Backend level comes from the probability-weighted risk score
                riskLevel.textContent = `${RISK_TEXT[serverDanger.risk_level] || serverDanger.risk_level} · ${Math.round((serverDanger.risk_score || 0) * 100)}%`;
            } else {
                riskLevel.textContent = matchedRules.some(r => r.risk === 'High') ? 'CAO' : 'TRUNG BÌNH CAO';
            }
            riskLevel.className = 'risk-badge badge-red';

            riskReasonContainer.style.display = 'block';
            dangerSignsList.innerHTML = '';

            // Print ALL matched danger signs in BOLD RED text
            matchedRules.forEach((rule, idx) => {
                const dangerItem = document.createElement('div');
                dangerItem.className = 'danger-rule-item';
                const conf = typeof rule.confidence === 'number' ? ` (tin cậy ${Math.round(rule.confidence * 100)}%)` : '';
                dangerItem.innerHTML = `
                    <span class="danger-rule-num">Dấu hiệu ${idx + 1}:</span>
                    <span class="danger-rule-desc bold-red-text">${rule.desc}${conf}</span>
                `;
                dangerSignsList.appendChild(dangerItem);
            });
            
            // Show target HUD overlay
            targetBox.style.display = 'flex';
            const hudText = targetBox.querySelector('.hud-center-text');
            if (hudText) {
                hudText.textContent = matchedRules.some(r => r.category === 'Threat Item') ? "WEAPON DETECTED" : "DANGER DETECTED";
            }
        } else {
            // Low Risk State
            alertWarning.style.display = 'none';
            alertSafe.style.display = 'flex';
            const safeTextContainer = alertSafe.querySelector('.alert-content p');
            if (safeTextContainer) {
                const pending = serverDanger && serverDanger.pending_rules && serverDanger.pending_rules[0];
                safeTextContainer.textContent = pending
                    ? `Đang xác minh: ${pending.desc}`
                    : "Không có dấu hiệu nguy hiểm";
            }
            
            riskBox.className = 'risk-assessment-section';
            riskLevel.textContent = 'THẤP';
            riskLevel.className = 'risk-badge badge-green';
            
            riskReasonContainer.style.display = 'none';
            dangerSignsList.innerHTML = '';
            
            // Hide target HUD
            targetBox.style.display = 'none';
        }
    }

    // Reset UI
    function resetUI() {
        attrGender.textContent = "Chưa có dữ liệu";
        attrAge.textContent = "Chưa có dữ liệu";
        attrHeight.textContent = "~175cm";
        attrUpper.textContent = "Chưa có dữ liệu";
        attrLower.textContent = "Chưa có dữ liệu";
        attrFootwear.textContent = "Chưa có dữ liệu";
        
        rowUpper.classList.remove('suspicious');
        rowLower.classList.remove('suspicious');

        accessoriesCount.textContent = "0 phát hiện";
        accessoriesList.innerHTML = `
            <div class="empty-accessories-state">
                <span>Chưa có dữ liệu</span>
            </div>
        `;

        alertWarning.style.display = 'none';
        alertSafe.style.display = 'flex';
        
        riskBox.className = 'risk-assessment-section';
        riskLevel.textContent = 'THẤP';
        riskLevel.className = 'risk-badge badge-green';
        riskReasonContainer.style.display = 'none';
        dangerSignsList.innerHTML = '';
        
        targetBox.style.display = 'none';
    }

    function setServerStatus(text, color) {
        serverStatusText.textContent = text;
        serverStatusIndicator.className = color ? "status-indicator online" : "status-indicator";
        serverStatusIndicator.style.backgroundColor = color || "#ef4444";
        serverStatusIndicator.style.boxShadow = color ? `0 0 8px ${color}` : "none";
    }

    // Place the HUD box over the real person bbox (video uses object-fit: cover)
    function positionTargetBox(bbox, frame) {
        if (!bbox || !frame || !frame.w || !frame.h || !videoContainer) return;
        const cw = videoContainer.clientWidth;
        const ch = videoContainer.clientHeight;
        const scale = Math.max(cw / frame.w, ch / frame.h);
        const offX = (cw - frame.w * scale) / 2;
        const offY = (ch - frame.h * scale) / 2;
        const [x0, y0, x1, y1] = bbox;
        targetBox.style.left = `${offX + x0 * scale}px`;
        targetBox.style.top = `${offY + y0 * scale}px`;
        targetBox.style.width = `${(x1 - x0) * scale}px`;
        targetBox.style.height = `${(y1 - y0) * scale}px`;
    }

    // Poll laptop backend: /api/person (target person + attributes) and /dets (FPS)
    async function fetchFromApi() {
        const [personRes, detsRes] = await Promise.all([
            fetch('/api/person', { cache: 'no-store' }),
            fetch('/dets', { cache: 'no-store' })
        ]);
        if (!personRes.ok || !detsRes.ok) throw new Error('API unavailable');
        const data = await personRes.json();
        const dets = await detsRes.json();

        if (fpsVal) fpsVal.textContent = Number(dets.fps || 0).toFixed(1);
        if (resVal && data.frame) resVal.textContent = `${data.frame.w}x${data.frame.h}`;
        if (personsVal) personsVal.textContent = `${data.tracks_count || 0}` + (data.suspicious_count ? ` (${data.suspicious_count} nghi vấn)` : '');
        if (engineStatus && data.attr) engineStatus.textContent = `AI: ${data.attr.engine || '--'}`;
        if (videoContainer && data.frame && data.frame.w && data.frame.h) {
            videoContainer.style.aspectRatio = `${data.frame.w} / ${data.frame.h}`;
        }

        if (!data.camera_ok) {
            setServerStatus("Camera laptop: không đọc được", null);
            if (analysisText) analysisText.textContent = "Không đọc được camera";
            resetUI();
            return;
        }
        setServerStatus("Camera laptop: Hoạt động", "var(--color-success)");

        // Scene alert: lens covered / blacked out (independent of any person)
        if (data.scene && data.scene.camera_occluded) {
            if (analysisText) analysisText.textContent = `Camera bị che ${data.scene.since_s}s`;
            updateUI(["cameraOcclusion"], {
                is_dangerous: true, risk_level: "High", risk_score: 1,
                matched_rules: [{ id: "S01", category: "Camera Tampering", risk: "High", desc: "Camera bị che / mất hình (nghi phá hoại camera)", confidence: 1 }],
                danger_labels: ["cameraOcclusion"], pending_rules: []
            });
            targetBox.style.display = 'none';
            return;
        }

        if (!data.person || !data.person.valid) {
            if (analysisText) analysisText.textContent = "Không phát hiện người";
            resetUI();
            return;
        }
        const labels = (data.positive_attributes || []).map(a => a.label);
        if (!data.attr || !data.attr.valid) {
            if (analysisText) analysisText.textContent = data.attr && data.attr.reason === 'bbox_too_small'
                ? `Người #${data.person.track_id} quá xa camera` : `Đang phân tích người #${data.person.track_id}...`;
            // Behaviour rules (running, fast approach...) can fire before / without attributes
            if (data.danger && data.danger.is_dangerous) {
                positionTargetBox(data.person.bbox, data.frame);
                updateUI(labels, data.danger);
            } else {
                resetUI();
            }
            return;
        }

        if (analysisText) analysisText.textContent = `Người #${data.person.track_id} · ${Math.round(data.attr.latency_ms)} ms`;
        // Backend already applied per-head thresholds + post-processing, so use every positive label.
        positionTargetBox(data.person.bbox, data.frame);  // before showing, avoids a one-frame flash
        updateUI(labels, data.danger);
    }

    // Fetch JSON file
    async function fetchAttributes() {
        if (isDemoMode) return;

        if (useApi) {
            try {
                await fetchFromApi();
                return;
            } catch (error) {
                console.warn("Backend API unavailable, falling back to JSON file:", error);
                if (analysisText) analysisText.textContent = "Mất kết nối máy chủ";
            }
        }

        try {
            const response = await fetch(targetFile);
            if (!response.ok) throw new Error('File not found');
            
            const data = await response.json();
            let labels = [];

            if (Array.isArray(data)) {
                labels = data;
            } else if (data && typeof data === 'object') {
                if (Array.isArray(data.positive_attributes)) {
                    labels = data.positive_attributes
                        .filter(attr => attr.prob >= 0.5)
                        .map(attr => attr.label);
                } else if (Array.isArray(data.active_labels)) {
                    labels = data.active_labels;
                } else if (Array.isArray(data.detected)) {
                    labels = data.detected;
                } else if (Array.isArray(data.labels) && !data.schema) {
                    labels = data.labels;
                } else if (data.schema && data.groups) {
                    if (Array.isArray(data.active)) {
                        labels = data.active;
                    } else {
                        console.log("Read schema, waiting for detections...");
                        return;
                    }
                } else {
                    for (const [key, value] of Object.entries(data)) {
                        if (value === true || value === 1 || (typeof value === 'number' && value > 0.5)) {
                            labels.push(key);
                        }
                    }
                }
            }

            console.log("Parsed active labels:", labels);
            updateUI(labels);
            
            serverStatusText.textContent = `File: ${targetFile}`;
            serverStatusIndicator.className = "status-indicator online";
            serverStatusIndicator.style.backgroundColor = "var(--color-success)";
            serverStatusIndicator.style.boxShadow = "0 0 8px var(--color-success)";

        } catch (error) {
            console.error("Error loading JSON:", error);
            serverStatusText.textContent = "Không tìm thấy file";
            serverStatusIndicator.className = "status-indicator";
            serverStatusIndicator.style.backgroundColor = "#ef4444";
            serverStatusIndicator.style.boxShadow = "none";
        }
    }

    // Demo Mode
    const DEMO_STATES = [
        {
            // Case 1: Normal Safe Subject
            labels: [
                "personalMale",
                "personalLess30",
                "upperBodyTshirt",
                "upperBodyWhite",
                "lowerBodyJeans",
                "lowerBodyBlue",
                "footwearSneaker",
                "footwearWhite",
                "maskNone",
                "glassesEyeglasses",
                "carryingNothing"
            ]
        },
        {
            // Case 2: Suspicious Subject (High Risk - Multiple Danger Signs)
            labels: [
                "personalMale",
                "personalLess30",
                "upperBodyJacket",
                "upperBodyBlack",
                "lowerBodyTrousers",
                "lowerBodyBlack",
                "footwearSneaker",
                "footwearBlack",
                "maskSurgical",
                "glassesSunglasses",
                "hatCap",
                "carryingBackpack"
            ]
        }
    ];

    function runDemoCycle() {
        if (!isDemoMode) return;
        
        console.log(`Running Demo Step: ${demoStep}`);
        const currentState = DEMO_STATES[demoStep];
        updateUI(currentState.labels);
        
        demoStep = (demoStep + 1) % DEMO_STATES.length;
    }

    settingsBtn.addEventListener('click', () => {
        isDemoMode = !isDemoMode;
        
        const toast = document.createElement('div');
        toast.style.position = 'fixed';
        toast.style.bottom = '24px';
        toast.style.right = '24px';
        toast.style.backgroundColor = isDemoMode ? 'var(--color-warning)' : 'var(--text-primary)';
        toast.style.color = '#fff';
        toast.style.padding = '12px 20px';
        toast.style.borderRadius = '8px';
        toast.style.boxShadow = 'var(--shadow-lg)';
        toast.style.zIndex = '1000';
        toast.style.fontFamily = 'var(--font-sans)';
        toast.style.fontSize = '13px';
        toast.style.fontWeight = '600';
        toast.style.animation = 'slide-down 0.3s ease-out';
        toast.textContent = isDemoMode ? "⚠️ Đã bật Chế độ Mô phỏng (Demo Mode)" : "🔄 Đã chuyển sang chế độ Đọc file JSON";
        
        document.body.appendChild(toast);
        setTimeout(() => toast.remove(), 2500);

        if (isDemoMode) {
            serverStatusText.textContent = "Máy chủ: Mô phỏng";
            serverStatusIndicator.className = "status-indicator online";
            serverStatusIndicator.style.backgroundColor = "var(--color-warning)";
            serverStatusIndicator.style.boxShadow = "0 0 8px var(--color-warning)";
            
            demoStep = 0;
            ['left', 'top', 'width', 'height'].forEach(k => targetBox.style.removeProperty(k));
            runDemoCycle();
            clearInterval(pollInterval);
            pollInterval = setInterval(runDemoCycle, 4000);
        } else {
            resetUI();
            if (!uploadInput) startPolling();
        }
    });

    function startPolling() {
        fetchAttributes();
        clearInterval(pollInterval);
        pollInterval = setInterval(fetchAttributes, useApi ? 500 : 1000);
    }


    // ---------- Upload mode (upload.html): POST /api/analyze, one result per person ----------
    function initUploadMode() {
        const drop = document.getElementById('upload-drop');
        const placeholder = document.getElementById('upload-placeholder');
        const chips = document.getElementById('person-chips');
        const nameEl = document.getElementById('upload-name');
        let result = null;

        resetUI();
        setServerStatus("Chế độ: Tải ảnh lên", "var(--color-success)");

        const pick = () => uploadInput.click();
        drop.addEventListener('click', pick);
        document.getElementById('upload-btn').addEventListener('click', pick);
        uploadInput.addEventListener('change', () => {
            if (uploadInput.files[0]) analyze(uploadInput.files[0]);
            uploadInput.value = '';
        });
        ['dragenter', 'dragover'].forEach(ev => drop.addEventListener(ev, e => {
            e.preventDefault();
            drop.classList.add('dragover');
        }));
        ['dragleave', 'drop'].forEach(ev => drop.addEventListener(ev, e => {
            e.preventDefault();
            drop.classList.remove('dragover');
        }));
        drop.addEventListener('drop', e => {
            const file = e.dataTransfer.files[0];
            if (file) analyze(file);
        });
        window.addEventListener('resize', () => {
            const active = chips.querySelector('.person-chip.active');
            if (result && active) select(result.persons[Number(active.dataset.idx)], Number(active.dataset.idx));
        });

        async function analyze(file) {
            nameEl.textContent = file.name;
            analysisText.textContent = "Đang phân tích...";
            chips.innerHTML = '';
            resetUI();
            const form = new FormData();
            form.append('file', file);
            try {
                const res = await fetch('/api/analyze', { method: 'POST', body: form });
                if (!res.ok) {
                    const err = await res.json().catch(() => ({}));
                    throw new Error(err.detail || res.statusText);
                }
                result = await res.json();
            } catch (error) {
                result = null;
                analysisText.textContent = `Lỗi: ${error.message}`;
                setServerStatus("Máy chủ: lỗi phân tích", null);
                return;
            }
            setServerStatus("Chế độ: Tải ảnh lên", "var(--color-success)");

            videoFeed.src = result.image;
            videoFeed.style.display = 'block';
            placeholder.style.display = 'none';
            videoContainer.style.aspectRatio = `${result.frame.w} / ${result.frame.h}`;
            resVal.textContent = `${result.frame.w}x${result.frame.h}`;
            const suspicious = result.persons.filter(p => p.danger.is_dangerous).length;
            personsVal.textContent = `${result.persons.length}` + (suspicious ? ` (${suspicious} nghi vấn)` : '');
            const withAttr = result.persons.find(p => p.attr.engine);
            if (withAttr) engineStatus.textContent = `AI: ${withAttr.attr.engine}`;

            if (result.persons.length === 0) {
                analysisText.textContent = "Không phát hiện người";
                return;
            }
            result.persons.forEach((p, idx) => {
                const chip = document.createElement('button');
                chip.type = 'button';
                chip.dataset.idx = idx;
                chip.className = `person-chip ${p.danger.is_dangerous ? 'danger' : ''}`;
                chip.textContent = `Người #${p.person.track_id}` + (p.danger.is_dangerous ? ' ⚠' : '');
                chip.addEventListener('click', () => select(p, idx));
                chips.appendChild(chip);
            });
            select(result.persons[0], 0);  // backend sorts by risk score
        }

        function select(p, idx) {
            chips.querySelectorAll('.person-chip').forEach(c => c.classList.toggle('active', Number(c.dataset.idx) === idx));
            if (!p.attr.valid) {
                resetUI();
                analysisText.textContent = `Người #${p.person.track_id} quá nhỏ để phân tích`;
                return;
            }
            analysisText.textContent = `Người #${p.person.track_id} · ${Math.round(p.attr.latency_ms)} ms`;
            updateUI((p.positive_attributes || []).map(a => a.label), p.danger);
            requestAnimationFrame(() => positionTargetBox(p.person.bbox, result.frame));
        }
    }

    if (uploadInput) {
        initUploadMode();
    } else {
        startPolling();
    }
});
