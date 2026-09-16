"""Phase D4 · Feb 2026 — checklist row-label translations.

Static translation matrix for every row shipped in
:data:`routers.industry_checklists.DEFAULT_TEMPLATES`. Keys are
``(industry, row_key)`` pairs; values are ``{ "es": str, "fr": str }``
maps. English lives in the row's ``label`` field on the template
document — it is the authoritative source of truth.

Design intent
=============
* Neutral Spanish / French phrasing (LatAm-neutral Spanish; Quebec-
  compatible French).
* Industry acronyms preserved where the trade uses them
  domain-wide (``HVAC``, ``GFCI``, ``AFCI``, ``PSI``, ``EPA``,
  ``PV``). Full-text expansions get lumped into the translator-review
  README so a pro can flip them per-market.
* No punctuation loss — the trailing ``…`` (U+2026) and the em-dash
  ``—`` are preserved verbatim.

Consumed by
===========
* ``services.migrations.seed_phase_d_industry_templates.run_phase_d1_industry_template_seed``
  when ``include_i18n=True`` — populates ``label_i18n.{es,fr}`` on
  every seeded default row.
* ``services.migrations.seed_phase_d4_checklist_row_translations`` —
  standalone D4-only migration that folds translations onto rows
  seeded by D1 without touching anything else.
"""
from __future__ import annotations

from typing import Dict, Tuple


# ══════════════════════════════════════════════════════════════════════
# ``(industry, row_key)`` → {"es": …, "fr": …}
# ══════════════════════════════════════════════════════════════════════
ROW_TRANSLATIONS: Dict[Tuple[str, str], Dict[str, str]] = {
    # ── pool ──────────────────────────────────────────────────────────
    ("pool", "skimmed_pool"):           {"es": "Piscina desnatada",                    "fr": "Piscine écumée"},
    ("pool", "brush_pool"):             {"es": "Cepillado de la piscina",              "fr": "Brossage de la piscine"},
    ("pool", "checked_skimmer_basket"): {"es": "Canasta del skimmer revisada",         "fr": "Panier de l'écumoire vérifié"},
    ("pool", "checked_pump_basket"):    {"es": "Canasta de la bomba revisada",         "fr": "Panier de la pompe vérifié"},
    ("pool", "tested_chemicals"):       {"es": "Productos químicos analizados",        "fr": "Produits chimiques testés"},
    ("pool", "checked_equipment"):      {"es": "Equipos revisados",                     "fr": "Équipement vérifié"},
    ("pool", "secured_all_gates"):      {"es": "Todas las puertas aseguradas",         "fr": "Toutes les portes verrouillées"},
    ("pool", "emptied_skimmer_basket"): {"es": "Canasta del skimmer vaciada",          "fr": "Panier de l'écumoire vidé"},
    ("pool", "emptied_leaf_canister"):  {"es": "Colector de hojas vaciado",             "fr": "Collecteur de feuilles vidé"},
    ("pool", "emptied_betta_skimmer"):  {"es": "Betta Skimmer vaciado",                 "fr": "Betta Skimmer vidé"},

    # ── landscaping ───────────────────────────────────────────────────
    ("landscaping", "mowed_lawn_areas"):         {"es": "Zonas de césped cortadas",              "fr": "Zones de pelouse tondues"},
    ("landscaping", "edged_walkways_driveways"): {"es": "Bordes de senderos y accesos recortados","fr": "Bordures des allées et entrées coupées"},
    ("landscaping", "trimmed_shrubs_hedges"):    {"es": "Arbustos y setos recortados",            "fr": "Arbustes et haies taillés"},
    ("landscaping", "blew_off_hardscape"):       {"es": "Superficies duras sopladas",             "fr": "Surfaces dures soufflées"},
    ("landscaping", "removed_weeds_from_beds"):  {"es": "Maleza retirada de los canteros",        "fr": "Mauvaises herbes retirées des massifs"},
    ("landscaping", "cleared_debris"):           {"es": "Escombros retirados del área de trabajo","fr": "Débris retirés de la zone de travail"},
    ("landscaping", "inspected_irrigation"):     {"es": "Aspersores de riego inspeccionados",     "fr": "Têtes d'irrigation inspectées"},
    ("landscaping", "bagged_removed_clippings"): {"es": "Recortes embolsados y retirados",        "fr": "Résidus de coupe ensachés et retirés"},
    ("landscaping", "applied_fertilizer"):       {"es": "Fertilizante o tratamiento aplicado",    "fr": "Engrais ou traitement appliqué"},

    # ── hvac ──────────────────────────────────────────────────────────
    ("hvac", "replaced_air_filter"):        {"es": "Filtro de aire reemplazado",              "fr": "Filtre à air remplacé"},
    ("hvac", "checked_thermostat"):         {"es": "Calibración del termostato verificada",   "fr": "Calibrage du thermostat vérifié"},
    ("hvac", "inspected_condensate_drain"): {"es": "Línea de drenaje de condensado inspeccionada","fr": "Conduite d'évacuation des condensats inspectée"},
    ("hvac", "cleaned_condenser_coils"):    {"es": "Serpentines del condensador limpiados",   "fr": "Serpentins du condenseur nettoyés"},
    ("hvac", "measured_refrigerant"):       {"es": "Presión del refrigerante medida",         "fr": "Pression du fluide frigorigène mesurée"},
    ("hvac", "checked_electrical"):         {"es": "Conexiones eléctricas revisadas",         "fr": "Connexions électriques vérifiées"},
    ("hvac", "verified_airflow"):           {"es": "Flujo de aire del sistema verificado",    "fr": "Débit d'air du système vérifié"},
    ("hvac", "tested_startup_shutdown"):    {"es": "Ciclo de arranque y apagado probado",     "fr": "Cycle de démarrage et d'arrêt testé"},
    ("hvac", "recorded_temp_differential"): {"es": "Diferencial de temperatura registrado",   "fr": "Différentiel de température consigné"},

    # ── pest_control ──────────────────────────────────────────────────
    ("pest_control", "treated_exterior_perimeter"): {"es": "Perímetro exterior tratado",              "fr": "Périmètre extérieur traité"},
    ("pest_control", "applied_interior_treatment"): {"es": "Tratamiento interior aplicado donde fue accesible", "fr": "Traitement intérieur appliqué là où c'était accessible"},
    ("pest_control", "inspected_bait_stations"):    {"es": "Estaciones de cebo inspeccionadas",       "fr": "Postes d'appâtage inspectés"},
    ("pest_control", "removed_spider_webs"):        {"es": "Telarañas accesibles retiradas",          "fr": "Toiles d'araignée accessibles retirées"},
    ("pest_control", "identified_entry_points"):    {"es": "Puntos de entrada identificados",         "fr": "Points d'entrée identifiés"},
    ("pest_control", "documented_pest_activity"):   {"es": "Actividad de plagas documentada",         "fr": "Activité des nuisibles documentée"},
    ("pest_control", "applied_granular_soil"):      {"es": "Tratamiento granular aplicado al suelo",  "fr": "Traitement granulaire appliqué au sol"},
    ("pest_control", "placed_monitoring_devices"):  {"es": "Dispositivos de monitoreo colocados",     "fr": "Dispositifs de surveillance installés"},
    ("pest_control", "documented_products_epa"):    {"es": "Productos aplicados documentados (n.º de registro EPA + cantidad)", "fr": "Produits appliqués documentés (n° d'enregistrement EPA + quantité)"},
    ("pest_control", "informed_reentry_time"):      {"es": "Cliente informado del tiempo de reingreso","fr": "Client informé du délai de retour"},

    # ── cleaning ──────────────────────────────────────────────────────
    ("cleaning", "high_dusted_surfaces"):       {"es": "Superficies altas desempolvadas",         "fr": "Surfaces en hauteur dépoussiérées"},
    ("cleaning", "wiped_countertops_surfaces"): {"es": "Encimeras y superficies limpiadas",       "fr": "Comptoirs et surfaces essuyés"},
    ("cleaning", "vacuumed_mopped_floors"):     {"es": "Pisos aspirados y trapeados",             "fr": "Sols aspirés et lavés à la vadrouille"},
    ("cleaning", "cleaned_restrooms"):          {"es": "Baños limpiados",                          "fr": "Toilettes nettoyées"},
    ("cleaning", "emptied_trash_bins"):         {"es": "Botes de basura vaciados",                "fr": "Poubelles vidées"},
    ("cleaning", "restocked_supplies"):         {"es": "Suministros reabastecidos",                "fr": "Fournitures réapprovisionnées"},
    ("cleaning", "cleaned_windows_glass"):      {"es": "Ventanas y cristales interiores limpiados","fr": "Vitres et surfaces vitrées intérieures nettoyées"},
    ("cleaning", "deodorized_common_areas"):    {"es": "Áreas comunes desodorizadas",             "fr": "Espaces communs désodorisés"},

    # ── solar ─────────────────────────────────────────────────────────
    ("solar", "inspected_panel_condition"): {"es": "Condición física de los paneles inspeccionada","fr": "État physique des panneaux inspecté"},
    ("solar", "verified_inverter_status"):  {"es": "Estado del inversor verificado",              "fr": "État de l'onduleur vérifié"},
    ("solar", "recorded_system_output"):    {"es": "Salida del sistema registrada",               "fr": "Production du système consignée"},
    ("solar", "cleaned_panel_surfaces"):    {"es": "Superficies de los paneles limpiadas si era necesario", "fr": "Surfaces des panneaux nettoyées si nécessaire"},
    ("solar", "checked_wiring_connections"):{"es": "Cableado y conexiones revisados",             "fr": "Câblage et connexions vérifiés"},
    ("solar", "inspected_mounting"):        {"es": "Herrajes de montaje inspeccionados",          "fr": "Fixations de montage inspectées"},
    ("solar", "reviewed_monitoring_portal"):{"es": "App / portal de monitoreo revisado",          "fr": "Application / portail de surveillance consulté"},
    ("solar", "documented_anomalies"):      {"es": "Anomalías documentadas",                       "fr": "Anomalies consignées"},

    # ── handyman ──────────────────────────────────────────────────────
    ("handyman", "confirmed_scope"):          {"es": "Alcance confirmado con el cliente",          "fr": "Portée confirmée avec le client"},
    ("handyman", "verified_tools_materials"): {"es": "Herramientas y materiales verificados en el sitio", "fr": "Outils et matériaux vérifiés sur place"},
    ("handyman", "completed_agreed_work"):    {"es": "Trabajo acordado completado",                "fr": "Travail convenu terminé"},
    ("handyman", "post_work_safety_walk"):    {"es": "Recorrido de seguridad posterior al trabajo realizado", "fr": "Ronde de sécurité post-travaux effectuée"},
    ("handyman", "cleaned_work_area"):        {"es": "Área de trabajo limpiada",                    "fr": "Zone de travail nettoyée"},
    ("handyman", "reviewed_with_customer"):   {"es": "Trabajo revisado con el cliente",             "fr": "Travail passé en revue avec le client"},
    ("handyman", "documented_before_after"):  {"es": "Fotos de antes/después documentadas",         "fr": "Photos avant/après documentées"},

    # ── plumbing ──────────────────────────────────────────────────────
    ("plumbing", "shutoff_valve_tested"):      {"es": "Válvula de cierre probada",                  "fr": "Robinet d'arrêt testé"},
    ("plumbing", "water_pressure_checked"):    {"es": "Presión del agua verificada (PSI)",          "fr": "Pression de l'eau vérifiée (PSI)"},
    ("plumbing", "fixtures_inspected_leaks"):  {"es": "Grifería inspeccionada por fugas",            "fr": "Robinetterie inspectée pour détecter des fuites"},
    ("plumbing", "drain_flow_verified"):       {"es": "Flujo del drenaje verificado",                "fr": "Écoulement des drains vérifié"},
    ("plumbing", "water_heater_inspected"):    {"es": "Calentador de agua inspeccionado",            "fr": "Chauffe-eau inspecté"},
    ("plumbing", "parts_materials_documented"):{"es": "Piezas / materiales utilizados documentados", "fr": "Pièces / matériaux utilisés documentés"},

    # ── electrical ────────────────────────────────────────────────────
    ("electrical", "panel_labeled_accessible"): {"es": "Panel etiquetado y accesible",               "fr": "Panneau étiqueté et accessible"},
    ("electrical", "voltage_readings_recorded"):{"es": "Lecturas de voltaje registradas",             "fr": "Relevés de tension consignés"},
    ("electrical", "gfci_afci_tested"):         {"es": "Tomacorrientes GFCI / AFCI probados",         "fr": "Prises GFCI / AFCI testées"},
    ("electrical", "wiring_inspected_damage"):  {"es": "Cableado inspeccionado por daños",            "fr": "Câblage inspecté pour détecter des dommages"},
    ("electrical", "grounding_verified"):       {"es": "Puesta a tierra verificada",                  "fr": "Mise à la terre vérifiée"},
    ("electrical", "circuits_load_tested"):     {"es": "Circuitos probados bajo carga",               "fr": "Circuits testés en charge"},
    ("electrical", "client_walkthrough_done"):  {"es": "Recorrido con el cliente completado",         "fr": "Visite guidée avec le client terminée"},

    # ── roofing ───────────────────────────────────────────────────────
    ("roofing", "roof_surface_inspection"): {"es": "Inspección de la superficie del techo",         "fr": "Inspection de la surface du toit"},
    ("roofing", "flashings_penetrations"):  {"es": "Tapajuntas y penetraciones revisadas",          "fr": "Solins et pénétrations vérifiés"},
    ("roofing", "gutters_drainage_clear"):  {"es": "Canaletas / drenaje despejados",                "fr": "Gouttières / évacuation dégagées"},
    ("roofing", "attic_ventilation"):       {"es": "Ventilación del ático verificada",              "fr": "Ventilation du grenier vérifiée"},
    ("roofing", "debris_removed"):          {"es": "Escombros retirados",                            "fr": "Débris retirés"},
    ("roofing", "trouble_spots_photos"):    {"es": "Fotos capturadas de puntos problemáticos",      "fr": "Photos des points problématiques prises"},
    ("roofing", "warranty_items_noted"):    {"es": "Elementos de garantía anotados",                "fr": "Éléments de garantie notés"},

    # ── painting ──────────────────────────────────────────────────────
    ("painting", "surface_prep_completed"):    {"es": "Preparación de superficies completada",       "fr": "Préparation des surfaces terminée"},
    ("painting", "primer_applied"):            {"es": "Imprimación aplicada donde fue necesario",     "fr": "Apprêt appliqué là où nécessaire"},
    ("painting", "coat_count_documented"):     {"es": "Cantidad de manos documentada",                "fr": "Nombre de couches documenté"},
    ("painting", "trim_edging_completed"):     {"es": "Molduras / bordes completados",                "fr": "Moulures / bordures terminées"},
    ("painting", "cleanup_completed"):         {"es": "Limpieza completada",                          "fr": "Nettoyage terminé"},
    ("painting", "client_walkthrough_signoff"):{"es": "Recorrido y aprobación del cliente",           "fr": "Visite finale et approbation du client"},

    # ── garage_door ───────────────────────────────────────────────────
    ("garage_door", "springs_cables_inspected"): {"es": "Resortes y cables inspeccionados",           "fr": "Ressorts et câbles inspectés"},
    ("garage_door", "opener_force_tested"):      {"es": "Configuración de fuerza del motor probada",  "fr": "Réglage de force du moteur testé"},
    ("garage_door", "safety_sensors_aligned"):   {"es": "Sensores de seguridad alineados y probados", "fr": "Capteurs de sécurité alignés et testés"},
    ("garage_door", "rollers_hinges_lubed"):     {"es": "Rodillos y bisagras lubricados",             "fr": "Galets et charnières lubrifiés"},
    ("garage_door", "weather_seal_condition"):   {"es": "Estado del sello de intemperie",             "fr": "État du joint d'étanchéité"},
    ("garage_door", "manual_release_tested"):    {"es": "Liberación manual probada",                  "fr": "Déblocage manuel testé"},

    # ── appliance_repair ──────────────────────────────────────────────
    ("appliance_repair", "model_serial_recorded"):    {"es": "Modelo / número de serie registrado",   "fr": "Modèle / numéro de série consigné"},
    ("appliance_repair", "symptom_reproduced"):       {"es": "Síntoma reproducido",                    "fr": "Symptôme reproduit"},
    ("appliance_repair", "parts_replaced_documented"):{"es": "Piezas reemplazadas documentadas",       "fr": "Pièces remplacées documentées"},
    ("appliance_repair", "voltage_continuity"):       {"es": "Lecturas de voltaje / continuidad",      "fr": "Relevés de tension / continuité"},
    ("appliance_repair", "function_tested_postrepair"):{"es": "Funcionamiento probado tras la reparación","fr": "Fonctionnement testé après la réparation"},
    ("appliance_repair", "client_demoed_operation"):  {"es": "Uso demostrado al cliente",              "fr": "Fonctionnement démontré au client"},

    # ── locksmith ─────────────────────────────────────────────────────
    ("locksmith", "lock_type_make_recorded"): {"es": "Tipo y marca de cerradura registrados",         "fr": "Type et marque de serrure consignés"},
    ("locksmith", "keys_cut_rekeyed_count"):  {"es": "Cantidad de llaves cortadas / recodificadas",   "fr": "Nombre de clés taillées / recodées"},
    ("locksmith", "deadbolt_verified"):       {"es": "Operación del cerrojo verificada",              "fr": "Fonctionnement du pêne dormant vérifié"},
    ("locksmith", "master_sub_keys_docs"):    {"es": "Llaves maestras / secundarias documentadas si aplica", "fr": "Clés maîtresses / secondaires documentées le cas échéant"},
    ("locksmith", "client_id_verified"):      {"es": "Verificación de identidad del cliente completada","fr": "Vérification d'identité du client effectuée"},

    # ── chimney_sweep ─────────────────────────────────────────────────
    ("chimney_sweep", "firebox_smoke_chamber"): {"es": "Hogar y cámara de humo inspeccionados",       "fr": "Foyer et chambre à fumée inspectés"},
    ("chimney_sweep", "creosote_level_noted"):  {"es": "Nivel de creosota registrado (0/1/2/3)",       "fr": "Niveau de créosote consigné (0/1/2/3)"},
    ("chimney_sweep", "cap_crown_inspected"):   {"es": "Sombrerete y corona inspeccionados",           "fr": "Chapeau et couronne inspectés"},
    ("chimney_sweep", "damper_operation"):      {"es": "Operación del regulador probada",              "fr": "Fonctionnement du registre testé"},
    ("chimney_sweep", "ash_debris_removed"):    {"es": "Ceniza / escombros retirados",                 "fr": "Cendres / débris retirés"},
    ("chimney_sweep", "draft_test_performed"):  {"es": "Prueba de tiro realizada",                     "fr": "Test de tirage effectué"},

    # ── gutter ────────────────────────────────────────────────────────
    ("gutter", "debris_cleared_runs"):    {"es": "Escombros retirados de los canales",              "fr": "Débris retirés des conduits"},
    ("gutter", "downspouts_flushed"):     {"es": "Bajantes enjuagadas",                              "fr": "Descentes rincées"},
    ("gutter", "flow_verified_outlets"):  {"es": "Flujo verificado en las salidas",                 "fr": "Écoulement vérifié aux sorties"},
    ("gutter", "hangers_brackets"):       {"es": "Ganchos / soportes inspeccionados",               "fr": "Crochets / supports inspectés"},
    ("gutter", "fascia_condition"):       {"es": "Estado de la fascia registrado",                  "fr": "État de la planche de rive consigné"},
    ("gutter", "screens_guards_checked"): {"es": "Mallas / protectores revisados si están instalados","fr": "Grilles / protections vérifiées si installées"},

    # ── window_cleaning ───────────────────────────────────────────────
    ("window_cleaning", "exterior_glass_cleaned"):  {"es": "Vidrios exteriores limpiados",           "fr": "Vitres extérieures nettoyées"},
    ("window_cleaning", "interior_glass_cleaned"):  {"es": "Vidrios interiores limpiados",           "fr": "Vitres intérieures nettoyées"},
    ("window_cleaning", "screens_removed_cleaned"): {"es": "Mosquiteros retirados y limpiados",      "fr": "Moustiquaires retirées et nettoyées"},
    ("window_cleaning", "sills_tracks_wiped"):      {"es": "Alféizares y rieles limpiados",          "fr": "Rebords et rails essuyés"},
    ("window_cleaning", "cracks_seal_issues"):      {"es": "Grietas / problemas de sellado anotados","fr": "Fissures / problèmes de joint notés"},
    ("window_cleaning", "streak_spot_recheck"):     {"es": "Nueva revisión de rayas / manchas completada", "fr": "Nouveau contrôle des traces / taches effectué"},

    # ── carpet_cleaning ───────────────────────────────────────────────
    ("carpet_cleaning", "pretreatment_applied"):     {"es": "Pretratamiento aplicado",                "fr": "Prétraitement appliqué"},
    ("carpet_cleaning", "hot_water_extraction"):     {"es": "Extracción con agua caliente completada","fr": "Extraction à l'eau chaude terminée"},
    ("carpet_cleaning", "spot_stain_treatments"):    {"es": "Tratamientos de manchas registrados",   "fr": "Traitements des taches consignés"},
    ("carpet_cleaning", "furniture_moved_restored"): {"es": "Muebles movidos / recolocados",          "fr": "Meubles déplacés / remis en place"},
    ("carpet_cleaning", "drying_time_communicated"): {"es": "Tiempo de secado comunicado al cliente", "fr": "Temps de séchage communiqué au client"},
    ("carpet_cleaning", "damage_noted_preservice"):  {"es": "Daños anotados antes del servicio",      "fr": "Dommages notés avant le service"},

    # ── pressure_washing ──────────────────────────────────────────────
    ("pressure_washing", "psi_setting_recorded"):     {"es": "Ajuste de PSI registrado",              "fr": "Réglage PSI consigné"},
    ("pressure_washing", "detergent_documented"):     {"es": "Detergentes / químicos usados documentados","fr": "Détergents / produits chimiques utilisés documentés"},
    ("pressure_washing", "surface_types_cleaned"):    {"es": "Tipos de superficies limpiadas",         "fr": "Types de surfaces nettoyées"},
    ("pressure_washing", "runoff_drainage_plan"):     {"es": "Plan de escurrimiento / drenaje seguido","fr": "Plan de ruissellement / drainage respecté"},
    ("pressure_washing", "damage_noted_preservice_pw"):{"es": "Daños anotados antes del servicio",     "fr": "Dommages notés avant le service"},
    ("pressure_washing", "final_rinse_completed"):    {"es": "Enjuague final completado",              "fr": "Rinçage final effectué"},

    # ── tree_service ──────────────────────────────────────────────────
    ("tree_service", "trees_serviced_species"):  {"es": "Árboles atendidos (especie / cantidad)",     "fr": "Arbres traités (espèce / nombre)"},
    ("tree_service", "work_performed_type"):     {"es": "Trabajo realizado (poda / tala / tocón)",     "fr": "Travail effectué (élagage / abattage / souche)"},
    ("tree_service", "debris_hauled_chipped"):   {"es": "Escombros retirados o triturados",            "fr": "Débris évacués ou déchiquetés"},
    ("tree_service", "drop_zone_verified"):      {"es": "Protección de propiedad / zona de caída verificada","fr": "Protection de la propriété / zone de chute vérifiée"},
    ("tree_service", "overhead_line_clearance"): {"es": "Distancia a las líneas eléctricas verificada","fr": "Dégagement des lignes aériennes vérifié"},
    ("tree_service", "client_walkthrough_tree"): {"es": "Recorrido con el cliente",                    "fr": "Visite guidée avec le client"},

    # ── snow_removal ──────────────────────────────────────────────────
    ("snow_removal", "areas_cleared_documented"): {"es": "Áreas despejadas documentadas",             "fr": "Zones dégagées documentées"},
    ("snow_removal", "deicer_applied"):           {"es": "Descongelante aplicado (producto y cantidad)","fr": "Fondant appliqué (produit et quantité)"},
    ("snow_removal", "site_conditions_arrival"):  {"es": "Condiciones del sitio a la llegada",         "fr": "Conditions du site à l'arrivée"},
    ("snow_removal", "site_conditions_departure"):{"es": "Condiciones del sitio a la salida",          "fr": "Conditions du site au départ"},
    ("snow_removal", "photos_property_damage"):   {"es": "Fotos tomadas (obligatorio si hay daños)",   "fr": "Photos prises (obligatoire en cas de dommages)"},
    ("snow_removal", "hazards_noted"):            {"es": "Peligros anotados",                          "fr": "Dangers notés"},

    # ── fencing ───────────────────────────────────────────────────────
    ("fencing", "posts_set_plumb"):          {"es": "Postes instalados / verificados a plomo",       "fr": "Poteaux installés / vérifiés d'aplomb"},
    ("fencing", "rails_pickets"):            {"es": "Travesaños y estacas instalados / reparados",   "fr": "Traverses et lattes posées / réparées"},
    ("fencing", "gate_operation_tested"):    {"es": "Operación de la puerta probada",                "fr": "Fonctionnement du portail testé"},
    ("fencing", "hardware_installed"):       {"es": "Herrajes instalados",                            "fr": "Quincaillerie installée"},
    ("fencing", "debris_cleaned_fence"):     {"es": "Escombros retirados",                            "fr": "Débris retirés"},
    ("fencing", "client_walkthrough_fence"): {"es": "Recorrido y aprobación del cliente",             "fr": "Visite finale et approbation du client"},

    # ── irrigation ────────────────────────────────────────────────────
    ("irrigation", "zones_cycled_tested"):    {"es": "Todas las zonas ciclado y probadas",           "fr": "Toutes les zones testées en cycle"},
    ("irrigation", "heads_adjusted_aligned"): {"es": "Aspersores ajustados y alineados",              "fr": "Têtes ajustées et alignées"},
    ("irrigation", "leaks_breaks_noted"):     {"es": "Fugas / roturas anotadas",                      "fr": "Fuites / bris consignés"},
    ("irrigation", "controller_programmed"):  {"es": "Controlador programado y documentado",          "fr": "Contrôleur programmé et documenté"},
    ("irrigation", "backflow_tested"):        {"es": "Antiretorno probado (si aplica)",               "fr": "Anti-refoulement testé (si applicable)"},
    ("irrigation", "winterize_step_logged"):  {"es": "Paso de invernaje / desinvernaje registrado",   "fr": "Étape d'hivernage / mise en service consignée"},
}


SUPPORTED_LOCALES = ("en", "es", "fr")


def get_row_translations(industry: str, key: str) -> Dict[str, str]:
    """Return the ``{es, fr}`` map for ``(industry, key)`` or an
    empty dict when the pair isn't translated yet."""
    return ROW_TRANSLATIONS.get((industry, key), {})
