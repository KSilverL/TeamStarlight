package com.example.tsldemo;

import jakarta.persistence.Entity;

@Entity
public class IntakeDTO {

	private String mode;
	private String openingInput;

	public String getMode() {
		return mode;
	}

	public void setMode(String mode) {
		this.mode = mode;
	}

	public String getOpeningInput() {
		return openingInput;
	}

	public void setOpeningInput(String openingInput) {
		this.openingInput = openingInput;
	}

    public IntakeDTO(String mode, String openingInput) {
		this.setMode(mode);
		this.setOpeningInput(openingInput);
	}
}
