# Pricebook `supplier_prices` backfill audit

*Generated: 2026-08-18T18:32:23.887964+00:00*

## Summary across all tenants

* Tenants scanned: **1**
* Total pricebook items: **1072**
* Empty `supplier_prices`: **518**
  * Hydratable (has non-zero `homeworks_costs`): **0**
  * Unresolved (no source data or all zeros): **518**

## Per-tenant breakdown

| tenant_id | total | empty | hydratable | unresolved | unmapped_supplier | has_homeworks_row |
|-----------|------:|------:|-----------:|-----------:|------------------:|:-----------------:|
| `3814833a-dd0…` | 1072 | 518 | 0 | 518 | 0 | yes |

## Unresolved items (need supplier-team follow-up)

### Tenant `3814833a-dd0d-4bd9-90ea-351c24924649` — 518 row(s)

| item_id | name | reason |
|---------|------|--------|
| `1b9a5693-6bc4-4e4f-a6c2-251cb3d25ff9` | Weekly Pool Cleaning | `no_homeworks_costs_blob` |
| `275d3aca-3ae4-4be3-bc9a-f0757e12a8ac` | Monthly Maintenance | `no_homeworks_costs_blob` |
| `61ceaede-297f-40f6-a81d-99cc819e47fd` | DE Filter Cartridge | `no_homeworks_costs_blob` |
| `c2d37138-b053-45db-85d3-2bb040f73411` | Chlorine Tablets (25 lb) | `no_homeworks_costs_blob` |
| `20f6e97e-c180-44c4-96a6-48620a27f8fa` | Labor | `no_homeworks_costs_blob` |
| `67c45e69-0103-46c9-8571-34cbbaf5739f` | Pool Salt (40 lb) | `no_homeworks_costs_blob` |
| `984f87c1-f62c-4c9a-ba37-f4ccd1321eb5` | PB Test Item | `no_homeworks_costs_blob` |
| `0acf43fa-d51f-4a78-bdb4-89c0acd2c223` | PB Test Item | `no_homeworks_costs_blob` |
| `04c3f042-ca6e-4550-8367-245cbb625f0f` | PB Test Item | `no_homeworks_costs_blob` |
| `d3325e52-b557-437f-bd4d-189906b2e038` | PB Test Item | `no_homeworks_costs_blob` |
| `714cbb61-3ebc-44ae-9619-05fcbaf4ca28` | PB Test Item | `no_homeworks_costs_blob` |
| `ffa96ce8-9680-4649-8b4d-5c2f7aace955` | PB Test Item | `no_homeworks_costs_blob` |
| `d7aac18c-63ab-4231-a319-ec10fbbd8605` | PB Test Item | `no_homeworks_costs_blob` |
| `a7c28dff-fb0e-4356-a710-5807f96f798b` | PB Test Item | `no_homeworks_costs_blob` |
| `dd3656cf-5179-4866-8e69-be0aee1a3b8d` | PB Test Item | `no_homeworks_costs_blob` |
| `55201196-72c2-40c1-8706-589317ee20de` | PB Test Item | `no_homeworks_costs_blob` |
| `03cb861a-0ea5-46da-a838-baed07bd101b` | PB Test Item | `no_homeworks_costs_blob` |
| `207de22c-f228-4c70-897e-7ea9175d8925` | PB Test Item | `no_homeworks_costs_blob` |
| `75fc98819b444da2a210e03693e13601` | KK-item-75fc98 | `no_homeworks_costs_blob` |
| `184fe841b30043bcb1cea4f4c81cc360` | KK-item-184fe8 | `no_homeworks_costs_blob` |
| `f3a2c4925f9f4b509f63ab34ed15e106` | KK-item-f3a2c4 | `no_homeworks_costs_blob` |
| `6c755fbca5d547648ac57262ab35de3d` | KK-bulk-6c755f | `no_homeworks_costs_blob` |
| `f9e59a23efb64274a20c022598d94fc8` | KK-bulk-f9e59a | `no_homeworks_costs_blob` |
| `03ede03ada1d4d60a78fe0216150fc02` | KK-bulk-03ede0 | `no_homeworks_costs_blob` |
| `a5608b49b27148029e50925281a6d2cd` | KK-locked-a5608b | `no_homeworks_costs_blob` |
| `2a9f7ea49c0247fdb5a09269ddbc0541` | KK-item-2a9f7e | `no_homeworks_costs_blob` |
| `a4b7fb77d5f54f1583b9e35bc828da31` | KK-item-a4b7fb | `no_homeworks_costs_blob` |
| `1d7668a7f0e64a0b989803c8cdeb74df` | KK-item-1d7668 | `no_homeworks_costs_blob` |
| `210f7129bfee4d7e9d37470082517151` | KK-bulk-210f71 | `no_homeworks_costs_blob` |
| `523e618164de45e58b5defe83b53ef4d` | KK-bulk-523e61 | `no_homeworks_costs_blob` |
| `6cfd22d6078a4c2db2e9711f2b38a25f` | KK-bulk-6cfd22 | `no_homeworks_costs_blob` |
| `2d937cdfab2c4211a1d40ded2db13bab` | KK-locked-2d937c | `no_homeworks_costs_blob` |
| `368156f38a1d4eb2b25ace43daa202ed` | KK-item-368156 | `no_homeworks_costs_blob` |
| `68ec86cb61d245b1831de035b43eb136` | KK-item-68ec86 | `no_homeworks_costs_blob` |
| `4fe8650395f344ceb32a441af6ee23a7` | KK-item-4fe865 | `no_homeworks_costs_blob` |
| `9c2e795bfe594220b97e92e9da6e80a1` | KK-bulk-9c2e79 | `no_homeworks_costs_blob` |
| `e254f5ea792249dc863ddd4ce0125932` | KK-bulk-e254f5 | `no_homeworks_costs_blob` |
| `46e1970799d04e3d95746a6d1580071c` | KK-bulk-46e197 | `no_homeworks_costs_blob` |
| `a30dd2db918c4d0a8f25a179fec01232` | KK-locked-a30dd2 | `no_homeworks_costs_blob` |
| `aac41179024f4f198005190da58cbe42` | KK-item-aac411 | `no_homeworks_costs_blob` |
| `a76ea8e94d6e427db31aa45c888657f9` | KK-item-a76ea8 | `no_homeworks_costs_blob` |
| `90e9762ae3ce4d16b94a5ac86540b16b` | KK-item-90e976 | `no_homeworks_costs_blob` |
| `a387a4579bf543b8ba902ece12411c29` | KK-bulk-a387a4 | `no_homeworks_costs_blob` |
| `59d1512d2c51403ab6dbe8681509aa5d` | KK-bulk-59d151 | `no_homeworks_costs_blob` |
| `f04b600ebfaf464a908475eecd00e0ab` | KK-bulk-f04b60 | `no_homeworks_costs_blob` |
| `695858b3cb154a2cb4b1c35cded1f564` | KK-locked-695858 | `no_homeworks_costs_blob` |
| `ae223ba0e1c34287a8782e0ef4ca9c57` | KK-item-ae223b | `no_homeworks_costs_blob` |
| `4142962d2ab9470396b58d9062fcd746` | KK-item-414296 | `no_homeworks_costs_blob` |
| `bd95b56c90d045e1a7a2947b26aa9edd` | KK-item-bd95b5 | `no_homeworks_costs_blob` |
| `f081343a581944adb4aac92fc44b72f9` | KK-bulk-f08134 | `no_homeworks_costs_blob` |
| `81d4a95a22314188bf8069ce1741f6be` | KK-bulk-81d4a9 | `no_homeworks_costs_blob` |
| `0c5e5cbf36b3413f88f566e2504ff9a7` | KK-bulk-0c5e5c | `no_homeworks_costs_blob` |
| `a7a4946ab7fc4707a916a6a4c4fed83e` | KK-locked-a7a494 | `no_homeworks_costs_blob` |
| `99a0c4fec8194096b4ed21f1d76d802d` | KK-item-99a0c4 | `no_homeworks_costs_blob` |
| `2b1dbd7fc76d42eb8bf9514cbff882e5` | KK-item-2b1dbd | `no_homeworks_costs_blob` |
| `2e824922ca174cf18ed09796f465fbce` | KK-item-2e8249 | `no_homeworks_costs_blob` |
| `23ecf6bec8d64e898c94b008967ed533` | KK-bulk-23ecf6 | `no_homeworks_costs_blob` |
| `7a46cf0dc31642de85bc06c93740ae05` | KK-bulk-7a46cf | `no_homeworks_costs_blob` |
| `77c1d96cfe7248ab9421e12a0ecac16b` | KK-bulk-77c1d9 | `no_homeworks_costs_blob` |
| `c2ea114810dd4330b89f9c6fcc946edb` | KK-locked-c2ea11 | `no_homeworks_costs_blob` |
| `7d176f6281ab4c3bae779c2fe7b365aa` | KK-item-7d176f | `no_homeworks_costs_blob` |
| `37a8f766ac85491a85b1f06a79d60b81` | KK-item-37a8f7 | `no_homeworks_costs_blob` |
| `6ccc491a92d441ffb2ae6b4a197599c9` | KK-item-6ccc49 | `no_homeworks_costs_blob` |
| `0feea8b77d2749fb86416af5626f5560` | KK-bulk-0feea8 | `no_homeworks_costs_blob` |
| `09185061746b4edd82a3b4c6fe40caef` | KK-bulk-091850 | `no_homeworks_costs_blob` |
| `8351fb74f3d743fd97d5428dc258eb94` | KK-bulk-8351fb | `no_homeworks_costs_blob` |
| `470620a5827748cba0ae789e20d86e15` | KK-locked-470620 | `no_homeworks_costs_blob` |
| `d97ad183e8954621aa32f00e0fe87a0f` | KK-item-d97ad1 | `no_homeworks_costs_blob` |
| `74a42dbd681d4deea885237741717a2c` | KK-item-74a42d | `no_homeworks_costs_blob` |
| `d5f990a3692c45a6a7b8d0fdc0e26e59` | KK-item-d5f990 | `no_homeworks_costs_blob` |
| `ceac5c59d3b64b93a567aeda575d71e9` | KK-bulk-ceac5c | `no_homeworks_costs_blob` |
| `cf00ff298f894ed1b649e66973248a70` | KK-bulk-cf00ff | `no_homeworks_costs_blob` |
| `cc8023d38ad94e2591f57517122d7b7c` | KK-bulk-cc8023 | `no_homeworks_costs_blob` |
| `27832a7c418f4c87a5825ec94eff4301` | KK-locked-27832a | `no_homeworks_costs_blob` |
| `05ec7beb59df43f18d780ecffb35e719` | KK-item-05ec7b | `no_homeworks_costs_blob` |
| `635e69a5d24c46e3a094ae4f7ef9669c` | KK-item-635e69 | `no_homeworks_costs_blob` |
| `1d22ae8a636441edbc5819258bb1b306` | KK-item-1d22ae | `no_homeworks_costs_blob` |
| `2be23288ac24428ea483358132e1a329` | KK-bulk-2be232 | `no_homeworks_costs_blob` |
| `e660f4f753ca471b9d40ee64c69f9af3` | KK-bulk-e660f4 | `no_homeworks_costs_blob` |
| `34190278056947f1a7408b755df3568d` | KK-bulk-341902 | `no_homeworks_costs_blob` |
| `10424774bf834e0aab8968c0ad18213d` | KK-locked-104247 | `no_homeworks_costs_blob` |
| `841f67d0251341eaa14855741071d4ea` | KK-item-841f67 | `no_homeworks_costs_blob` |
| `2e161e7aa42a451f9686b69a1c9fbfad` | KK-item-2e161e | `no_homeworks_costs_blob` |
| `376bb0e1d5b84beba101f20b0aa56dd2` | KK-item-376bb0 | `no_homeworks_costs_blob` |
| `460e12be3b144a73a75fb46984cdefb9` | KK-bulk-460e12 | `no_homeworks_costs_blob` |
| `da0c14553bfb49409c062f442dcbb3ec` | KK-bulk-da0c14 | `no_homeworks_costs_blob` |
| `97d7db07d6cf465495fc22e107d43117` | KK-bulk-97d7db | `no_homeworks_costs_blob` |
| `e38aacdbe7274f47a81ff05631767a9e` | KK-locked-e38aac | `no_homeworks_costs_blob` |
| `a0bbf9535cef40cd9aecc645fecd2588` | KK-item-a0bbf9 | `no_homeworks_costs_blob` |
| `f39e468d3ac942fa85db394fa4a9b54f` | KK-item-f39e46 | `no_homeworks_costs_blob` |
| `ca57d9e04abb4cc29d3b2b0d936d91fc` | KK-item-ca57d9 | `no_homeworks_costs_blob` |
| `e7fbf3b1a5194527b2305439c12bdd0d` | KK-bulk-e7fbf3 | `no_homeworks_costs_blob` |
| `bc10ed4877dd45a7952ea6eca024dacb` | KK-bulk-bc10ed | `no_homeworks_costs_blob` |
| `3baa860eda594cc5a77b6c8b5931b6ed` | KK-bulk-3baa86 | `no_homeworks_costs_blob` |
| `fbe1ff697e184497b82440bef01d0a7a` | KK-locked-fbe1ff | `no_homeworks_costs_blob` |
| `e278e098bb2542009255d768ef5140d0` | KK-item-e278e0 | `no_homeworks_costs_blob` |
| `bcf9b2e46ace4f009a4bde5af7a2f56e` | KK-item-bcf9b2 | `no_homeworks_costs_blob` |
| `c6f5f50aa6554dc4ae4983e3b22276a5` | KK-item-c6f5f5 | `no_homeworks_costs_blob` |
| `da41cdbfb15344c482c56850a3e0701e` | KK-bulk-da41cd | `no_homeworks_costs_blob` |
| `c60a6fd34a98439b91b38e8533646d26` | KK-bulk-c60a6f | `no_homeworks_costs_blob` |
| `c201831a6dee486f8c413a1351fd1f93` | KK-bulk-c20183 | `no_homeworks_costs_blob` |
| `ec9108229c2843f08b6c4132186e958d` | KK-locked-ec9108 | `no_homeworks_costs_blob` |
| `ba0509650f8e426ba8fdf422ec85267b` | KK-item-ba0509 | `no_homeworks_costs_blob` |
| `0a1cf4ab4a484911908c02fe5bddb1fd` | KK-item-0a1cf4 | `no_homeworks_costs_blob` |
| `e56aa0f6dab74c1c90121024dde7787d` | KK-item-e56aa0 | `no_homeworks_costs_blob` |
| `7c37c3eae9b443e99566f86b0b0fe3cb` | KK-bulk-7c37c3 | `no_homeworks_costs_blob` |
| `2410cbb658a845d8bcaba5f31682c5a2` | KK-item-2410cb | `no_homeworks_costs_blob` |
| `a4df0dd45fcd47328d137fb012e4eb83` | KK-item-a4df0d | `no_homeworks_costs_blob` |
| `842088cf296a4b9c825254e8f0cb1740` | KK-item-842088 | `no_homeworks_costs_blob` |
| `c61e57b85dc24c5c8e679a5723e31455` | KK-bulk-c61e57 | `no_homeworks_costs_blob` |
| `fd321b2b10794b1da724a08f9e98dc7a` | KK-bulk-fd321b | `no_homeworks_costs_blob` |
| `4f22a01ba86f4ad1b64a77b4b28346af` | KK-bulk-4f22a0 | `no_homeworks_costs_blob` |
| `4c298be786ad4f53891140081b87b424` | KK-locked-4c298b | `no_homeworks_costs_blob` |
| `2f78403cac6b432a911b9ef59a1efc91` | KK-item-2f7840 | `no_homeworks_costs_blob` |
| `f31e46a60f1c406ba1a3b98264cda54f` | KK-item-f31e46 | `no_homeworks_costs_blob` |
| `59fe9ae1e7d345b58d632c8af1d0ac4f` | KK-item-59fe9a | `no_homeworks_costs_blob` |
| `ebca703fdec6436d985d50ae9d81c0ff` | KK-bulk-ebca70 | `no_homeworks_costs_blob` |
| `b089566051e14ab79af2a34fc7d67e69` | KK-bulk-b08956 | `no_homeworks_costs_blob` |
| `bbcb6f6539424544a86e9a2eebdcb456` | KK-bulk-bbcb6f | `no_homeworks_costs_blob` |
| `220fb2740f734e2a9ad428cfa8d71773` | KK-locked-220fb2 | `no_homeworks_costs_blob` |
| `5a312e3c1a9e458da29d7d43bd6cd8c8` | KK-item-5a312e | `no_homeworks_costs_blob` |
| `c1329ecc662c467d88753d4e88355196` | KK-item-c1329e | `no_homeworks_costs_blob` |
| `74dbdaefc0da46bd83914ebd3fb26bb7` | KK-item-74dbda | `no_homeworks_costs_blob` |
| `8ed2bc2252164dac8401ed33c9c66d42` | KK-bulk-8ed2bc | `no_homeworks_costs_blob` |
| `ab83f2ddd89745dd97df049289c7d19d` | KK-bulk-ab83f2 | `no_homeworks_costs_blob` |
| `159136e138cb44c0b32c66a4ce96075c` | KK-bulk-159136 | `no_homeworks_costs_blob` |
| `0ebaa973f26643d0a7ccdb5b331b07be` | KK-locked-0ebaa9 | `no_homeworks_costs_blob` |
| `f9ccc38d80ab43f486ddba7835de60a7` | KK-item-f9ccc3 | `no_homeworks_costs_blob` |
| `a177ed2fff9b4ef581c698788adfebf3` | KK-item-a177ed | `no_homeworks_costs_blob` |
| `f0d3cad9fbee4a858f2fb7558540af22` | KK-item-f0d3ca | `no_homeworks_costs_blob` |
| `2815e61d0e99480a974caf87b156ff3a` | KK-bulk-2815e6 | `no_homeworks_costs_blob` |
| `27cec48e1df647688ddad8491f5935a7` | KK-bulk-27cec4 | `no_homeworks_costs_blob` |
| `fed039635820491a94cfd5810a2e9d8e` | KK-bulk-fed039 | `no_homeworks_costs_blob` |
| `2334651a083b44e5a7e9a5fdf47855a9` | KK-locked-233465 | `no_homeworks_costs_blob` |
| `7d0f73edac0e40f09ffea8ca1c980692` | KK-item-7d0f73 | `no_homeworks_costs_blob` |
| `792e1a5f687541e2b863cf8093ca5e7a` | KK-item-792e1a | `no_homeworks_costs_blob` |
| `e28c1b7b0ea54e529d45dce33a880708` | KK-item-e28c1b | `no_homeworks_costs_blob` |
| `1cfea604ecb047c296c98e8c438e1110` | KK-bulk-1cfea6 | `no_homeworks_costs_blob` |
| `2e5dfa3abda14bc2ae3262f3cb440980` | KK-bulk-2e5dfa | `no_homeworks_costs_blob` |
| `0716ed35098e4edf8e58454ba094b659` | KK-bulk-0716ed | `no_homeworks_costs_blob` |
| `c4d937d03d6e4cf793adb9afd3a8a14e` | KK-locked-c4d937 | `no_homeworks_costs_blob` |
| `7cff97e76f1243e1bba642a55baaeb85` | KK-item-7cff97 | `no_homeworks_costs_blob` |
| `f540547522f74261baf531f974f658fe` | KK-item-f54054 | `no_homeworks_costs_blob` |
| `e3c7c4553aa74326bc24430a53dd71ba` | KK-item-e3c7c4 | `no_homeworks_costs_blob` |
| `6d14388d1f57412e88b7dbc3d1778aed` | KK-bulk-6d1438 | `no_homeworks_costs_blob` |
| `2f681a035723476d975c34d4a30eed4b` | KK-bulk-2f681a | `no_homeworks_costs_blob` |
| `18beffc6630043c6aa5760ed6ff0ae7a` | KK-bulk-18beff | `no_homeworks_costs_blob` |
| `3b0eddfce7084485a52fd7f2cd911e0c` | KK-locked-3b0edd | `no_homeworks_costs_blob` |
| `de48e5d87d8e4cd3bd9571393e3eddb2` | KK-item-de48e5 | `no_homeworks_costs_blob` |
| `5178e95bd9dd4231b2455d5ee3b2bd3e` | KK-item-5178e9 | `no_homeworks_costs_blob` |
| `bc88552f232f46dca864096d3bd7935f` | KK-item-bc8855 | `no_homeworks_costs_blob` |
| `495316d721ec408a89b6f1697fc7c84c` | KK-bulk-495316 | `no_homeworks_costs_blob` |
| `e07a5ab49ad94f54a1845b5aaaabfdca` | KK-bulk-e07a5a | `no_homeworks_costs_blob` |
| `9e2b902c1c8d4f1faaae585248400cd7` | KK-bulk-9e2b90 | `no_homeworks_costs_blob` |
| `e3a4fb7e7a36442e9690febb8f77aded` | KK-locked-e3a4fb | `no_homeworks_costs_blob` |
| `fd82a5ecde8e4450a6e72d5be784c803` | KK-item-fd82a5 | `no_homeworks_costs_blob` |
| `97678e21f8224820ada80bb5062785be` | KK-item-97678e | `no_homeworks_costs_blob` |
| `11759b7cd12240cca10599a61166ab07` | KK-item-11759b | `no_homeworks_costs_blob` |
| `92a73483dda8474cb7de70bbd40d3944` | KK-bulk-92a734 | `no_homeworks_costs_blob` |
| `34f286e6f9dd4dc89d544e91bceb6c89` | KK-bulk-34f286 | `no_homeworks_costs_blob` |
| `23d5b81595084c71acd9ef29fda28a2c` | KK-bulk-23d5b8 | `no_homeworks_costs_blob` |
| `fd4d3b4c474045018689fd9da802afa0` | KK-locked-fd4d3b | `no_homeworks_costs_blob` |
| `fb7fdd0d81764ba7a103a10b26aeca41` | KK-item-fb7fdd | `no_homeworks_costs_blob` |
| `6b948e9656844a69b4f60a9a0b73f1a8` | KK-item-6b948e | `no_homeworks_costs_blob` |
| `41a9df624c80430e9752aa600d909277` | KK-item-41a9df | `no_homeworks_costs_blob` |
| `6702a239281940558482b115bb631955` | KK-bulk-6702a2 | `no_homeworks_costs_blob` |
| `7d04bd9c795d489181139f210746626e` | KK-bulk-7d04bd | `no_homeworks_costs_blob` |
| `038671317c5a40709d09b67ecc09731f` | KK-bulk-038671 | `no_homeworks_costs_blob` |
| `031a08a365d7472bbc3ac863570123bf` | KK-locked-031a08 | `no_homeworks_costs_blob` |
| `147f9e05c2d14206a6881f3b666f9a87` | KK-item-147f9e | `no_homeworks_costs_blob` |
| `2638690f8fac485fa2d701174c43bb1a` | KK-item-263869 | `no_homeworks_costs_blob` |
| `42eeea2195124f72a7cda5bd8f54362d` | KK-item-42eeea | `no_homeworks_costs_blob` |
| `a71d83c8a6824b81b71f520ee434e248` | KK-bulk-a71d83 | `no_homeworks_costs_blob` |
| `3d815a61b95f4600a0907160e9319165` | KK-bulk-3d815a | `no_homeworks_costs_blob` |
| `468c8f56149b4b36b62da9288ebffbe3` | KK-bulk-468c8f | `no_homeworks_costs_blob` |
| `3b5a0228b1ed4b42af93fe887f8470de` | KK-locked-3b5a02 | `no_homeworks_costs_blob` |
| `134b4f035ae0413997c584702d10e346` | KK-item-134b4f | `no_homeworks_costs_blob` |
| `02e76a9eac8e441cbf54a7cd57ea9ee8` | KK-item-02e76a | `no_homeworks_costs_blob` |
| `0d016ad605aa451cbd5c1a848b2b7831` | KK-item-0d016a | `no_homeworks_costs_blob` |
| `29c19740e683485cade81d8d6983cf3d` | KK-bulk-29c197 | `no_homeworks_costs_blob` |
| `04e8725447ca4fd7aec1efc592cf8dda` | KK-bulk-04e872 | `no_homeworks_costs_blob` |
| `3e57aacc56c24effad2bc415edbda179` | KK-bulk-3e57aa | `no_homeworks_costs_blob` |
| `6a553c7861e94a15a3dd7befcc2cbf54` | KK-locked-6a553c | `no_homeworks_costs_blob` |
| `c9dd2bdef88a42e5b380f67c0ef79b9e` | KK-item-c9dd2b | `no_homeworks_costs_blob` |
| `744a90e1565e4629937a6c3c04a6a5f3` | KK-item-744a90 | `no_homeworks_costs_blob` |
| `3de9f90f1cc74ec8b28ffb6ac45cb5e3` | KK-item-3de9f9 | `no_homeworks_costs_blob` |
| `3a8f04e199cf4e46a493bc2aca5b8486` | KK-bulk-3a8f04 | `no_homeworks_costs_blob` |
| `db3989984848428da1f8c3b234e7d88b` | KK-bulk-db3989 | `no_homeworks_costs_blob` |
| `2d8635a3393b440394fa9eb5d51ac7cb` | KK-bulk-2d8635 | `no_homeworks_costs_blob` |
| `171c9242f0ca4834aad4a895bc6ff833` | KK-locked-171c92 | `no_homeworks_costs_blob` |
| `74fd254a74024b3793672c2748c58cb0` | KK-item-74fd25 | `no_homeworks_costs_blob` |
| `ad56f47a8e064048ace193be307fa5fa` | KK-item-ad56f4 | `no_homeworks_costs_blob` |
| `3d7db5ab7b694498a1df8ccd0711b7df` | KK-item-3d7db5 | `no_homeworks_costs_blob` |
| `ab05fb9bbe654d98ac580d78c0f993c0` | KK-bulk-ab05fb | `no_homeworks_costs_blob` |
| `443c009e45e648b19f9cef4d6c1ca659` | KK-item-443c00 | `no_homeworks_costs_blob` |
| `9c351eb627184dd5a93c40268da499f2` | KK-item-9c351e | `no_homeworks_costs_blob` |
| `0e8ac8a9101449ba9e522276a12461a3` | KK-item-0e8ac8 | `no_homeworks_costs_blob` |
| `acba6b6c268a4e049fba0458c565fdd7` | KK-bulk-acba6b | `no_homeworks_costs_blob` |
| `0f66bda9289e41688a3452b189937db9` | KK-bulk-0f66bd | `no_homeworks_costs_blob` |
| `687e615dfb3d4a9485bc1daffdfbe878` | KK-bulk-687e61 | `no_homeworks_costs_blob` |
| … | +318 more | … |
