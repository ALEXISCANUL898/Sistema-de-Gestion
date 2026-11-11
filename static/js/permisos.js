/**
 * Permisos Module - API Integration for Permission Management
 * Handles all operations related to user permissions and system access
 */

const permisos = {
  API_BASE_URL: "",
  SISTEMA_CODIGO: "Tik_GES",

  /**
   * Obtiene el token actual del localStorage
   */
  getToken() {
    return localStorage.getItem("access_token");
  },

  /**
   * Obtiene headers con autenticación
   */
  getAuthHeaders(additionalHeaders = {}) {
    const token = this.getToken();
    if (!token) {
      throw new Error("No hay token de autenticación");
    }
    return {
      "Content-Type": "application/json",
      "Authorization": `Bearer ${token}`,
      ...additionalHeaders,
    };
  },

  /**
   * Valida que el usuario sea admin antes de hacer operaciones
   */
  async validarAccesoAdmin() {
    try {
      const response = await auth.fetchWithAuth(
        `${this.API_BASE_URL}/api/permisos/validar-permiso/`,
        {
          method: "POST",
          body: JSON.stringify({
            codigo_sistema: this.SISTEMA_CODIGO,
            nivel_minimo: 5
          }),
        }
      );

      if (!response.ok) {
        throw new Error("No tienes acceso a esta operación");
      }

      const data = await response.json();
      const esAdmin = data.roles?.some((rol) => rol.nivel_acceso === 3);
      
      if (!esAdmin) {
        throw new Error("Solo administradores pueden realizar esta acción");
      }

      return true;
    } catch (error) {
      console.error("Error validando acceso admin:", error);
      throw error;
    }
  },

  /**
   * Obtiene la lista de usuarios sin permisos para un sistema
   * @param {string} sistemaCodigo - Código del sistema (defecto: Tik_GES)
   * @returns {Promise<Object>} Objeto con usuarios_sin_permisos y total
   */
  async obtenerUsuariosSinPermisos(sistemaCodigo = this.SISTEMA_CODIGO) {
    try {
      console.log(`📋 Obteniendo usuarios sin permisos para ${sistemaCodigo}...`);
      
      const url = `${this.API_BASE_URL}/api/permisos/usuarios-sin-permisos/?sistema_codigo=${sistemaCodigo}`;
      const response = await auth.fetchWithAuth(url, { method: "GET" });

      if (!response.ok) {
        const errorData = await response.json();
        
        if (response.status === 403) {
          throw new Error("❌ Solo administradores pueden ver esto");
        }
        if (response.status === 404) {
          throw new Error(`❌ Sistema '${sistemaCodigo}' no encontrado`);
        }
        
        throw new Error(errorData.error || "Error al obtener usuarios");
      }

      const data = await response.json();
      console.log(`✓ ${data.total} usuarios sin permisos encontrados`);
      return data;
    } catch (error) {
      console.error("Error obteniendo usuarios sin permisos:", error);
      throw error;
    }
  },

  /**
   * Asigna un permiso a un usuario
   * @param {string} username - Nombre de usuario
   * @param {string} sistemaCodigo - Código del sistema
   * @param {string} rolNombre - Nombre del rol (defecto: Usuarios)
   * @returns {Promise<Object>} Objeto con resultado de la operación
   */
  async asignarPermiso(
    username,
    sistemaCodigo = this.SISTEMA_CODIGO,
    rolNombre = "Usuarios"
  ) {
    try {
      console.log(
        `🔐 Asignando permiso a ${username} en ${sistemaCodigo}...`
      );

      const url = `${this.API_BASE_URL}/api/permisos/asignar-permiso/`;
      const body = {
        username: username,
        sistema_codigo: sistemaCodigo,
        rol_nombre: rolNombre,
      };

      const response = await auth.fetchWithAuth(url, {
        method: "POST",
        body: JSON.stringify(body),
      });

      if (!response.ok) {
        const errorData = await response.json();
        
        if (response.status === 403) {
          throw new Error("❌ Solo administradores pueden asignar permisos");
        }
        if (response.status === 404) {
          if (errorData.error.includes("Usuario")) {
            throw new Error(`❌ Usuario '${username}' no encontrado`);
          }
          if (errorData.error.includes("Sistema")) {
            throw new Error(`❌ Sistema '${sistemaCodigo}' no encontrado`);
          }
          if (errorData.error.includes("Rol")) {
            throw new Error(
              `❌ Rol '${rolNombre}' no encontrado para este sistema`
            );
          }
        }
        
        throw new Error(
          errorData.error || "Error al asignar permiso"
        );
      }

      const data = await response.json();
      console.log(`✓ Permiso asignado exitosamente: ${data.message}`);
      return data;
    } catch (error) {
      console.error("Error asignando permiso:", error);
      throw error;
    }
  },

  /**
   * Obtiene todos los usuarios del sistema (para seleccionar en UI)
   * @returns {Promise<Array>} Array de usuarios
   */
  async obtenerUsuarios() {
    try {
      const response = await auth.fetchWithAuth(
        `${this.API_BASE_URL}/api/users/`,
        { method: "GET" }
      );

      if (!response.ok) {
        throw new Error("Error al obtener usuarios");
      }

      const data = await response.json();
      return data;
    } catch (error) {
      console.error("Error obteniendo usuarios:", error);
      return [];
    }
  },

  /**
   * Obtiene información del sistema actual del usuario
   * @returns {Promise<Object>} Información del sistema
   */
  async obtenerMisPerfil() {
    try {
      const response = await auth.fetchWithAuth(
        `${this.API_BASE_URL}/api/permisos/mi-perfil/`,
        { method: "GET" }
      );

      if (!response.ok) {
        throw new Error("Error al obtener perfil");
      }

      const data = await response.json();
      return data;
    } catch (error) {
      console.error("Error obteniendo perfil:", error);
      throw error;
    }
  },

  /**
   * Obtiene los sistemas a los que tiene acceso el usuario
   * @returns {Promise<Array>} Array de sistemas
   */
  async obtenerMisSistemas() {
    try {
      const response = await auth.fetchWithAuth(
        `${this.API_BASE_URL}/api/permisos/mis-sistemas/`,
        { method: "GET" }
      );

      if (!response.ok) {
        throw new Error("Error al obtener sistemas");
      }

      const data = await response.json();
      return data;
    } catch (error) {
      console.error("Error obteniendo sistemas:", error);
      return [];
    }
  },
};

// Exponer globalmente
window.permisos = permisos;
