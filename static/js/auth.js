/**
 * Auth Helper for API Integration
 */
const API_BASE_URL = "";

const auth = {
  setTokens(access, refresh) {
    localStorage.setItem("access_token", access);
    localStorage.setItem("refresh_token", refresh);
  },

  getAccessToken() {
    return localStorage.getItem("access_token");
  },

  getRefreshToken() {
    return localStorage.getItem("refresh_token");
  },

  clearTokens() {
    localStorage.removeItem("access_token");
    localStorage.removeItem("refresh_token");
    localStorage.removeItem("user_data");
  },

  async login(username, password) {
    const response = await fetch(`${API_BASE_URL}/api/permisos/login/`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ username, password }),
    });

    if (!response.ok) {
      const errorData = await response.json();
      
      // Manejar caso específico de usuario sin permisos
      if (response.status === 403) {
        throw new Error("Usuario sin permisos asignados");
      }
      
      throw new Error(errorData.error || "Login failed");
    }

    const data = await response.json();
    this.setTokens(data.access, data.refresh);
    localStorage.setItem("user_data", JSON.stringify(data.user));
    localStorage.setItem("permisos", JSON.stringify(data.permisos || []));
    return data;
  },

  async refreshToken() {
    const refresh = this.getRefreshToken();
    if (!refresh) throw new Error("No refresh token");

    const response = await fetch(
      `${API_BASE_URL}/api/permisos/token/refresh/`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ refresh }),
      },
    );

    if (!response.ok) {
      this.clearTokens();
      throw new Error("Session expired");
    }

    const data = await response.json();
    localStorage.setItem("access_token", data.access);
    return data.access;
  },

  async fetchWithAuth(url, options = {}) {
    let token = this.getAccessToken();
    if (!token) {
        window.location.href = "/accounts/login/";
        throw new Error("Not authenticated");
    }

    let headers = {
      ...options.headers,
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    };

    let response = await fetch(url, { ...options, headers });

    // 1. Manejar sesión expirada (401)
    if (response.status === 401) {
      try {
        token = await this.refreshToken();
        headers["Authorization"] = `Bearer ${token}`;
        response = await fetch(url, { ...options, headers });
      } catch (error) {
        window.location.href = "/accounts/login/";
        throw error;
      }
    }

    // 2. Manejar falta de permisos (403) según Guía API v3
    if (response.status === 403) {
        alert("No tienes permiso para ver esta sección.");
        window.location.href = "/iahelp/dashboard/"; // O el dashboard principal
        return response;
    }

    return response;
  },

  /**
   * Checks if the user has a minimum access level for a system
   * Logic: 1=Visualization, 2=Create/Update, 3=Superuser (High Priority)
   */
  async hasPermissionLevel(codigoSistema, minRequiredLevel) {
    try {
      const response = await this.fetchWithAuth(
        `${API_BASE_URL}/api/permisos/validar-permiso/`,
        {
          method: "POST",
          body: JSON.stringify({ 
            codigo_sistema: codigoSistema,
            nivel_minimo: minRequiredLevel || 5
          }),
        },
      );

      if (!response.ok) return false;

      const data = await response.json();
      if (!data.tiene_acceso || !data.roles || data.roles.length === 0)
        return false;

      // Check if any assigned role meets the level
      return data.roles.some((rol) => rol.nivel_acceso >= minRequiredLevel);
    } catch (error) {
      console.error("Error checking permissions:", error);
      return false;
    }
  },
};

window.auth = auth;
